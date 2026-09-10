import importlib.util
import os
import sqlite3
import sys
import datetime
import json
import smtplib

import subprocess
import sys
import math
subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "--ignore-installed"])

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify
from urllib.parse import quote

# Para poder importar user_account desde el directorio padre
PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))

PRODUCT_IMAGES_DIR = os.environ.get(
    'PRODUCT_IMAGES_DIR',
    '/data/product_images'
)

os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)

PARENT_DIR = os.path.abspath(os.path.join(PROJECT_DIR, '..'))
sys.path.insert(0, PARENT_DIR)

from user_account import create_account, init_db as init_user_db, verify_login, get_user_role, create_reset_token, reset_password as reset_user_password

# Importar Proyecto.1.G.py usando importlib porque el nombre de archivo no es un módulo válido
PROYECT_PATH = os.path.join(PROJECT_DIR, 'Proyecto.1.G.py')
spec = importlib.util.spec_from_file_location('proyecto_g', PROYECT_PATH)
proyecto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proyecto)

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('FLASK_SECRET', 'dev-flask-key')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

@app.route('/product-images/<path:filename>')
def product_image(filename):
    from flask import send_from_directory
    return send_from_directory(PRODUCT_IMAGES_DIR, filename)

MARKET = proyecto.crear_tiendas_demo()
init_user_db()
proyecto.init_db()
# Catálogo persistente: /data/marketplace.db
# No volver a sembrar datos demo automáticamente.


def get_store(store_id):
    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, nombre, direccion, celular, giro, codigo_postal
            FROM tiendas
            WHERE id = ?
        ''', (store_id,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        tienda = proyecto.Tienda(
            row['nombre'],
            row['direccion'],
            row['celular'],
            row['giro']
        )

        tienda.codigo_postal = row[5]

        cursor.execute('''
            SELECT
                id,
                nombre,
                unidades,
                precio,
                presentacion,
                imagen
            FROM productos
            WHERE tienda_id = ?
            ORDER BY id ASC
        ''', (store_id,))

        productos = cursor.fetchall()
        conn.close()

        for producto_row in productos:
            producto = proyecto.Producto(
                producto_row['nombre'],
                producto_row['unidades'],
                producto_row['precio'],
                producto_row['presentacion'],
                producto_row['imagen']
            )

            # Guardamos el ID real de SQLite en el objeto
            producto.id = producto_row['id']

            tienda.agregar_producto(producto)

        tienda.id = store_id

        return tienda

    except Exception as e:
        print('ERROR CARGANDO TIENDA DESDE DB:', e)
        return None


def get_product(store_id, product_id):
    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                p.id,
                p.tienda_id,
                p.nombre,
                p.unidades,
                p.precio,
                p.presentacion,
                p.imagen
            FROM productos p
            WHERE p.id = ?
              AND p.tienda_id = ?
        ''', (product_id, store_id))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        producto = proyecto.Producto(
            row['nombre'],
            row['unidades'],
            row['precio'],
            row['presentacion'],
            row['imagen']
        )

        producto.id = row['id']
        producto.tienda_id = row['tienda_id']

        return producto

    except Exception as e:
        print('ERROR CARGANDO PRODUCTO DESDE DB:', e)
        return None


def get_cart():
    return session.setdefault('cart', [])


def save_cart(cart):
    session['cart'] = cart

def get_cart_store_keys():
    groups = set()
    for item in get_cart():
        if item.get('custom'):
            tienda = (item.get('tienda') or '').strip().lower()
            groups.add(tienda)
        else:
            tienda_obj = get_store(item.get('store_id'))
            if tienda_obj:
                nombre = getattr(tienda_obj, 'nombre', '').strip().lower()
                groups.add(nombre)
    return list(groups)

def calculate_store_switch_fee(cart):
    groups = set()
    for item in cart:
        if item.get('custom'):
            tienda = (item.get('tienda') or '').strip()
            direccion = (item.get('direccion') or '').strip()
            groups.add((tienda, direccion))
        else:
            tienda = get_store(item.get('store_id'))
            if tienda:
                groups.add((getattr(tienda, 'nombre', '').strip(), getattr(tienda, 'direccion', '').strip()))
    extra_stores = max(len(groups) - 1, 0)
    return 50 * extra_stores

# ==========================================
# DISTANCIAS PARA ENTREGA URGENTE - MVP
# ==========================================

BASE_CP_TUUX = "97314"

# ==========================================
# CONTEXTO DE DESTINO
# ==========================================

DESTINATION_CONTEXTS = {
    "LOCAL_MERIDA": {
        "cps": {"97000", "97314"},
    },
    "MUNICIPIOS_CALKINI": {
        "cps": {"24900"},
    },
}

# ==========================================
# 5B.5D — EVALUACIÓN DE ESPACIO CALKINÍ
# ==========================================

LOGISTICS_SIZE_ORDER = {
    "CHICO": 1,
    "MEDIANO": 2,
    "GRANDE": 3,
}


def assess_calkini_order_space(order_items):
    """
    Resume la composición logística de un pedido
    para su posterior evaluación física en Calkiní.

    No calcula todavía el precio del taxi ni convierte
    automáticamente unidades entre tamaños.
    """

    counts = {
        "CHICO": 0,
        "MEDIANO": 0,
        "GRANDE": 0,
        "SIN_CLASIFICAR": 0,
    }

    max_size = None

    for item in order_items:
        unidades = int(item.get("unidades", 0) or 0)
        logistics_size = (item.get("logistics_size") or "").strip().upper()

        if logistics_size not in LOGISTICS_SIZE_ORDER:
            counts["SIN_CLASIFICAR"] += unidades
            continue

        counts[logistics_size] += unidades

        if (
            max_size is None
            or LOGISTICS_SIZE_ORDER[logistics_size]
            > LOGISTICS_SIZE_ORDER[max_size]
        ):
            max_size = logistics_size

    return {
        "counts": counts,
        "max_size": max_size,
        "total_unidades": sum(counts.values()),
        "requires_manual_assessment": (
            counts["SIN_CLASIFICAR"] > 0
        ),
    }

def determine_required_calkini_space(order_items):
    """
    Determina el tamaño mínimo de espacio requerido
    según el mayor tamaño logístico presente en el pedido.

    No convierte unidades pequeñas en espacios mayores.
    La compactación física se evaluará posteriormente.
    """

    assessment = assess_calkini_order_space(order_items)

    if assessment["requires_manual_assessment"]:
        return {
            "required_space": None,
            "reason": "SIN_CLASIFICAR",
            "assessment": assessment,
        }

    return {
        "required_space": assessment["max_size"],
        "reason": "MAYOR_TAMANO_PRESENTE",
        "assessment": assessment,
    }

def estimate_calkini_packed_space(order_items):
    """
    Estima el espacio físico requerido para un pedido Calkiní
    usando las capacidades de compactación validadas físicamente
    por TU'UX.

    Reglas actuales:
    - 1 a 16 CHICO -> MEDIANO
    - 17 o más CHICO -> GRANDE
    - 1 MEDIANO + hasta 8 CHICO -> MEDIANO
    - 2 o más MEDIANO -> GRANDE
    - Cualquier GRANDE -> GRANDE
    """

    counts = {
        "CHICO": 0,
        "MEDIANO": 0,
        "GRANDE": 0,
        "SIN_CLASIFICAR": 0,
    }

    for item in order_items:
        unidades = int(item.get("unidades", 0) or 0)
        logistics_size = (item.get("logistics_size") or "").strip().upper()

        if logistics_size not in counts:
            counts["SIN_CLASIFICAR"] += unidades
            continue

        counts[logistics_size] += unidades

    if counts["SIN_CLASIFICAR"] > 0:
        return {
            "required_space": None,
            "reason": "SIN_CLASIFICAR",
            "counts": counts,
        }

    if counts["GRANDE"] > 0:
        required_space = "GRANDE"

    elif counts["MEDIANO"] >= 2:
        required_space = "GRANDE"

    elif counts["MEDIANO"] == 1:
        if counts["CHICO"] <= 8:
            required_space = "MEDIANO"
        else:
            required_space = "GRANDE"

    elif counts["CHICO"] > 0:
        if counts["CHICO"] <= 16:
            required_space = "MEDIANO"
        else:
            required_space = "GRANDE"

    else:
        required_space = None

    return {
        "required_space": required_space,
        "reason": "COMPACTACION_VALIDADA",
        "counts": counts,
    }


def get_destination_context(delivery_cp):
    """
    Identifica el contexto operativo a partir del código postal
    de destino.
    """
    cp = normalize_cp(delivery_cp)

    if not cp:
        return {
            "context": "UNSUPPORTED",
            "delivery_cp": None,
        }

    for context_name, context_data in DESTINATION_CONTEXTS.items():
        if cp in context_data["cps"]:
            return {
                "context": context_name,
                "delivery_cp": cp,
            }

    return {
        "context": "UNSUPPORTED",
        "delivery_cp": cp,
    }

# Distancias estimadas entre códigos postales.
# Se irán ampliando conforme validemos operaciones reales.
CP_DISTANCES_KM = {
    ("97314", "97000"): 12.0,
    ("97000", "97314"): 12.0,
}


def normalize_cp(cp):
    """Normaliza un código postal a texto de 5 dígitos."""
    if cp is None:
        return None

    cp = str(cp).strip()

    if not cp.isdigit() or len(cp) != 5:
        return None

    return cp


def get_distance_km(cp_origen, cp_destino):
    """
    Devuelve la distancia estimada entre dos códigos postales.
    Por ahora usamos una tabla configurable para el MVP.
    """
    origen = normalize_cp(cp_origen)
    destino = normalize_cp(cp_destino)

    if not origen or not destino:
        raise ValueError("Código postal inválido.")

    if origen == destino:
        return 0.0

    distancia = CP_DISTANCES_KM.get((origen, destino))

    if distancia is None:
        distancia = CP_DISTANCES_KM.get((destino, origen))

    if distancia is None:
        raise ValueError(
            f"No tenemos todavía una distancia configurada entre "
            f"{origen} y {destino}."
        )

    return float(distancia)


def calculate_operation_distance_km(origin_cps, destination_cp):
    """
    Calcula los kilómetros de la operación:

    Base TU'UX → Tienda A → Tienda B → ... → Cliente

    No incluye el regreso a la base.
    """
    destination_cp = normalize_cp(destination_cp)

    if not destination_cp:
        raise ValueError("Código postal de destino inválido.")

    route = [BASE_CP_TUUX]

    for cp in origin_cps:
        cp = normalize_cp(cp)

        if not cp:
            raise ValueError("Uno de los códigos postales de origen es inválido.")

        route.append(cp)

    route.append(destination_cp)

    total_km = 0.0

    for i in range(len(route) - 1):
        total_km += get_distance_km(route[i], route[i + 1])

    return round(total_km, 2)

URGENT_KM_RATE = 4.20


def calculate_urgent_distance_cost(distance_km):
    """
    Calcula el costo de la parte de distancia
    de una entrega urgente.
    """
    if distance_km < 0:
        raise ValueError("La distancia no puede ser negativa.")

    return round(distance_km * URGENT_KM_RATE, 2)

def calculate_urgent_shipping_cost_from_operation(distance_km):
    return calculate_urgent_shipping_cost(
        distance_km,
        URGENT_ESTIMATED_MINUTES
    )

URGENT_TIME_RATE = 100
URGENT_TIME_BLOCK_MINUTES = 15
URGENT_ESTIMATED_MINUTES = 60


def calculate_urgent_time_cost(minutes):
    """
    Calcula el costo del tiempo ocupado para una entrega urgente.

    Tarifa:
    $100 por hora
    Cobro en bloques de 15 minutos.
    """
    if minutes < 0:
        raise ValueError("El tiempo no puede ser negativo.")

    if minutes == 0:
        return 0.0

    blocks = math.ceil(minutes / URGENT_TIME_BLOCK_MINUTES)
    billed_minutes = blocks * URGENT_TIME_BLOCK_MINUTES

    return round(
        billed_minutes * (URGENT_TIME_RATE / 60),
        2
    )

def calculate_urgent_shipping_cost(distance_km, minutes):
    distance_cost = calculate_urgent_distance_cost(distance_km)
    time_cost = calculate_urgent_time_cost(minutes)

    return round(distance_cost + time_cost, 2)


def build_cart_items():
    cart = get_cart()
    items = []
    total = 0
    for index, entry in enumerate(cart):
        if entry.get('custom'):
            items.append({
                'custom': True,
                'tienda': entry.get('tienda'),
                'direccion': entry.get('direccion'),
                'producto': entry.get('producto'),
                'cantidad': entry['cantidad'],
                'detalles': entry.get('detalles'),
                'subtotal': 0,
                'item_index': index,
            })
            continue
        # Si la entrada del carrito tiene un snapshot serializable del producto,
        # úsalo para calcular subtotal y mostrar datos aunque el producto cambie.
        if entry.get('producto') and isinstance(entry.get('producto'), dict):
            tienda = get_store(entry.get('store_id'))
            snapshot = entry.get('producto')
            precio = snapshot.get('precio', 0)
            subtotal = precio * entry.get('cantidad', 0)
            total += subtotal
            items.append({
                'tienda': tienda,
                'producto': snapshot,
                'cantidad': entry.get('cantidad', 0),
                'subtotal': subtotal,
                'store_id': entry.get('store_id'),
                'product_id': entry.get('product_id'),
                'item_index': index,
            })
            continue
        tienda = get_store(entry['store_id'])
        producto = get_product(entry['store_id'], entry['product_id'])
        if not tienda or not producto:
            continue
        subtotal = producto.precio * entry['cantidad']
        total += subtotal
        items.append({
            'tienda': tienda,
            'producto': producto,
            'cantidad': entry['cantidad'],
            'subtotal': subtotal,
            'store_id': entry['store_id'],
            'product_id': entry['product_id'],
            'item_index': index,
        })
    return items, total

def get_origin_cps_from_cart(items):
    origin_cps = set()

    for item in items:
        if item.get('custom'):
            continue

        tienda_obj = item.get('tienda')

        if tienda_obj:
            codigo_postal = getattr(tienda_obj, 'codigo_postal', None)

            if codigo_postal:
                codigo_postal = normalize_cp(codigo_postal)
                if codigo_postal:
                    origin_cps.add(codigo_postal)

    return sorted(origin_cps)

@app.route('/remove/<int:item_index>', methods=['POST'])
def remove_from_cart(item_index):
    cart = get_cart()
    if 0 <= item_index < len(cart):
        cart.pop(item_index)
        save_cart(cart)
        flash('Producto eliminado del carrito.')
    else:
        flash('Elemento del carrito no encontrado.')
    return redirect(url_for('cart'))


@app.route('/')
def index():
    return redirect(url_for('market'))
    

@app.route("/confirmar_pedido", methods=['POST'])
def confirmar_pedido():
    # Construir los items y total del carrito actual
    items, total = build_cart_items()
    
    if not items:
        flash('El carrito está vacío.')
        return redirect(url_for('cart'))

    # Verificar si hay productos personalizados (custom) desde marketlist
    cart = get_cart()
    tiene_custom = any(item.get('custom') for item in cart)
    
    
    # Validar opciones enviadas desde el formulario
    delivery_type = request.form.get('delivery_type')
    delivery_cp = request.form.get('delivery_cp', '').strip()
    destination_context_form = request.form.get('destination_context', '').strip().upper()

    print("📍 CP DESTINO RECIBIDO:", delivery_cp)

    delivery_selected = delivery_type == 'delivery'
    other_day_selected = delivery_type == 'other_day'
    urgent_selected = delivery_type == 'urgent'

    if not delivery_selected and not other_day_selected and not urgent_selected:
        flash('Selecciona una opción de entrega.')
        return redirect(url_for('cart'))

    # Mérida:
    # - Programada = tarifa local por tiempo
    # - Otro día = tarifa local por tiempo
    # - Urgente = fórmula propia por distancia + tiempo
    shipping_cost = 0

    if destination_context_form == 'MUNICIPIOS_CALKINI':

        if delivery_selected:
            shipping_cost = 50

        elif other_day_selected:
            shipping_cost = 110

        elif urgent_selected:
            shipping_cost = 0

    else:

        if delivery_selected:
            shipping_cost = 45

        elif other_day_selected:
            shipping_cost = 95

        elif urgent_selected:
            # aquí continúa el cálculo urgente que ya tienes
        
            origin_cps = get_origin_cps_from_cart(items)
            print("📍 CPs DE ORIGEN:", origin_cps)

            distance_km = calculate_operation_distance_km(
                 origin_cps,
                delivery_cp
            )

            print("📍 DISTANCIA OPERATIVA:", distance_km, "km")

            distance_cost = calculate_urgent_distance_cost(distance_km)
            print("💰 COSTO POR DISTANCIA:", distance_cost)

            time_cost = calculate_urgent_time_cost(URGENT_ESTIMATED_MINUTES)
            print("⏱️ COSTO POR TIEMPO:", time_cost)

            shipping_cost = round(distance_cost + time_cost, 2)
            print("🚚 TARIFA URGENTE TOTAL:", shipping_cost)
    
    total_a_pagar = total + shipping_cost

    # ==========================================
    # 5B.2 — Persistir pedido antes de WhatsApp
    # ==========================================
    market_request = session.get('market_request', {}) or {}
    username = session.get('username') or market_request.get('celular') or 'anonimo'

    if destination_context_form in ('LOCAL_MERIDA', 'MUNICIPIOS_CALKINI'):
        destination_context = {
            'context': destination_context_form
        }
    else:
        destination_context = get_destination_context(delivery_cp)
    
    if destination_context.get('context') == 'MUNICIPIOS_CALKINI':
        shipping_initial = 50
        logistics_status = 'PENDING_ASSESSMENT'
    else:
        shipping_initial = shipping_cost
        logistics_status = 'NOT_APPLICABLE'

    logistics_estimated_space = None
    logistics_assessment = None

    if destination_context.get('context') == 'MUNICIPIOS_CALKINI':
        logistics_items = []

        for item in items:
            if item.get('custom'):
                continue

            producto_data = item.get('producto')

            if isinstance(producto_data, dict):
                logistics_size = producto_data.get('logistics_size')
            else:
                logistics_size = getattr(producto_data, 'logistics_size', None)

            logistics_items.append({
                'unidades': item.get('cantidad', 0),
                'logistics_size': logistics_size
            })

        logistics_result = determine_required_calkini_space(logistics_items)

        logistics_estimated_space = logistics_result.get('required_space')
        logistics_assessment = json.dumps(
            logistics_result.get('assessment', {}),
            ensure_ascii=False
        )

    with proyecto._connect() as conn:
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO pedidos (
                username,
                total,
                created_at,
                destination_context,
                delivery_cp,
                shipping_initial,
                logistics_status,
                logistics_estimated_space,
                logistics_assessment,
                calkini_locality
                
                
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            username,
            total_a_pagar,
            datetime.datetime.now().isoformat(),
            destination_context.get('context'),
            delivery_cp,
            shipping_initial,
            logistics_status,
            logistics_estimated_space,
            logistics_assessment,
            request.form.get('calkini_locality', '').strip()
           
        ))

        pedido_id = cursor.lastrowid

        # ==========================================
        # 5B.3 — Persistir productos del pedido
        # ==========================================
        for item in items:
            if item.get('custom'):
                continue

            producto_id = item.get('product_id')
            unidades = item.get('cantidad', 0)

            producto_data = item.get('producto')

            if isinstance(producto_data, dict):
                precio = producto_data.get('precio', 0)
                logistics_size = producto_data.get('logistics_size')
            else:
                precio = getattr(producto_data, 'precio', 0)
                logistics_size = getattr(producto_data, 'logistics_size', None)

            if not producto_id or unidades <= 0:
                continue

            cursor.execute('''
                INSERT INTO pedido_items (
                    pedido_id,
                    producto_id,
                    unidades,
                    precio,
                    logistics_size
                )
                VALUES (?, ?, ?, ?, ?)
            ''', (
                pedido_id,
                producto_id,
                unidades,
                precio,
                logistics_size
            ))

    print("🧾 PEDIDO PERSISTIDO:", pedido_id)
    print("📦 ITEMS DEL PEDIDO PERSISTIDOS")
    print("🔥 5B.3 EJECUTADO CORRECTAMENTE")

    # Agrupar items por tienda y dirección
    tiendas_dict = {}
    for item in items:
        if item.get('custom'):
            tienda_nombre = item.get('tienda') or 'Tienda personalizada'
            direccion = item.get('direccion', '')
        else:
            tienda_obj = item.get('tienda')
            tienda_nombre = getattr(tienda_obj, 'nombre', 'Tienda Desconocida') if tienda_obj else 'Tienda Desconocida'
            direccion = getattr(tienda_obj, 'direccion', '') if tienda_obj else ''
        
        store_key = (tienda_nombre, direccion)
        if store_key not in tiendas_dict:
            tiendas_dict[store_key] = {
                'tienda_nombre': tienda_nombre,
                'direccion': direccion,
                'items': []
            }
        tiendas_dict[store_key]['items'].append(item)
    
    # Construir el mensaje dinámico con los datos reales
    market_request = session.get('market_request', {}) or {}
    nombre_cliente = (market_request.get('nombre') or '').strip()
    celular_cliente = (market_request.get('celular') or '').strip()
    municipio_cliente = (market_request.get('municipio') or '').strip()
    
    SEPARADOR = "________________________\n"
    mensaje = ""
    if nombre_cliente or celular_cliente or municipio_cliente:
        if nombre_cliente:
            mensaje += f"Nombre: {nombre_cliente}\n"
        if celular_cliente:
            mensaje += f"Celular: {celular_cliente}\n"
        if municipio_cliente:
            mensaje += f"Municipio: {municipio_cliente}\n"
        mensaje += SEPARADOR + "\n"
    
    mensaje += "¡Hola! 👋\n\nTu'ux tengo un encargo para ti.\n" " \nPedido:\n\n"
    
    # Iterar por tiendas agrupadas
    for (tienda_nombre, direccion), tienda_data in tiendas_dict.items():
        mensaje += f"📍 {tienda_nombre}"
        if direccion:
            mensaje += f" ({direccion})"
        mensaje += "\n"
        

        
        for item in tienda_data['items']:
            cantidad = item.get('cantidad', 0)
            detalles = item.get('detalles', '').strip()
            if item.get('custom'):
                producto = item['producto']
                if detalles:
                    mensaje += f"- {producto} ({detalles}) x{cantidad}\n"
                else:
                    mensaje += f"- {producto} x{cantidad}\n"
            else:
                producto_data = item['producto']
                if isinstance(producto_data, dict):
                    nombre = producto_data.get('nombre') or 'Producto'
                    presentacion = producto_data.get('presentacion', '') or ''
                else:
                    nombre = getattr(producto_data, 'nombre', 'Producto')
                    presentacion = getattr(producto_data, 'presentacion', '') or ''
                label = nombre
                if presentacion:
                    label += f" ({presentacion})"
                if detalles:
                    label += f" ({detalles})"
                mensaje += f"- {label} x{cantidad}\n"
        
        mensaje += "\n"
        

    
    # Agregar servicios aceptados después del último producto
    mensaje += SEPARADOR + "\n"
    
    
    mensaje += f"- Subtotal de productos: ${total:.2f} MXN\n"
    if delivery_selected:
        mensaje += f"🚚 Servicio de compra y entrega programada: ${shipping_cost:.2f} MXN\n"

    if other_day_selected:
        mensaje += f"🚚 Servicio de compra y entrega otro día: ${shipping_cost:.2f} MXN\n"

    if urgent_selected:
        mensaje += f"🚨 Servicio de compra y entrega urgente: ${shipping_cost:.2f} MXN\n"
        
    mensaje += SEPARADOR + "\n"

    if tiene_custom:
        mensaje += f"⚠️ Nota: Falta anexar servicios pendientes y total de los productos personalizados.\n"
        mensaje += "* El TOTAL FINAL a pagar será confirmado una vez que Tu'ux verifique disponibilidad de productos."
    else:
        mensaje += f"💵 TOTAL A PAGAR: ${total_a_pagar:.2f} MXN\n"
        if total_a_pagar > 2000:
            mensaje += "- Mi compra excede el límite permitido"

    # Enviar siempre al número fijo de WhatsApp
    numero = "525588182650"
    
    # Asegurarse de que el número solo contiene dígitos
    numero = ''.join(filter(str.isdigit, numero))
    
    mensaje_codificado = quote(mensaje)
    url = f"https://wa.me/{numero}?text={mensaje_codificado}"

    # Enviar copia del pedido por correo
    #try:
    #    order_info_email = {
    #        'items': items,
    #        'total': total_a_pagar,
    #        'direccion': direccion if delivery_selected else 'Punto de entrega',
    #        'detalles': mensaje,
    #        'delivery_type': delivery_type,
    #        'urgent': urgent_selected,
    #    }
    #    send_order_email(order_info_email, recipient_email='faac_clocks@hotmail.com')
   # except Exception as e:
    #    print('Error enviando copia de pedido por email:', e)

    return redirect(url)

# ==========================================
# 5B.5D-3B — REGISTRO DE ESPACIO REAL CALKINÍ
# ==========================================

@app.route('/admin/pedidos-calkini', methods=['GET', 'POST'])
def admin_pedidos_calkini():

    if not session.get('username'):
        return redirect(url_for('login'))

    # Guardar espacio físico real después de preparar el pedido
    if request.method == 'POST':

        pedido_id = request.form.get('pedido_id', '').strip()
        actual_space = request.form.get('actual_space', '').strip().upper()

        if actual_space not in ('CHICO', 'MEDIANO', 'GRANDE'):
            flash('Selecciona un espacio físico válido.')
            return redirect(url_for('admin_pedidos_calkini'))

        try:
            pedido_id = int(pedido_id)
        except ValueError:
            flash('Pedido no válido.')
            return redirect(url_for('admin_pedidos_calkini'))

        try:
            with proyecto._connect() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE pedidos
                    SET
                        logistics_actual_space = ?,
                        logistics_status = 'ASSESSED'
                    WHERE id = ?
                      AND destination_context = 'MUNICIPIOS_CALKINI'
                ''', (
                    actual_space,
                    pedido_id
                ))

                if cursor.rowcount == 0:
                    flash('No se encontró el pedido Calkiní.')
                    return redirect(url_for('admin_pedidos_calkini'))

            flash(f'✅ Pedido #{pedido_id}: espacio real registrado como {actual_space}.')

        except Exception as e:
            print('ERROR REGISTRANDO ESPACIO REAL CALKINÍ:', e)
            flash('Ocurrió un error al registrar el espacio real.')

        return redirect(url_for('admin_pedidos_calkini'))

    # Consultar pedidos Calkiní
    try:
        with proyecto._connect() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    id,
                    created_at,
                    total,
                    shipping_initial,
                    logistics_status,
                    logistics_estimated_space,
                    logistics_actual_space
                FROM pedidos
                WHERE destination_context = 'MUNICIPIOS_CALKINI'
                ORDER BY id DESC
            ''')

            pedidos = cursor.fetchall()

    except Exception as e:
        print('ERROR CARGANDO PEDIDOS CALKINÍ:', e)
        pedidos = []
        flash('No fue posible cargar los pedidos.')

    html = '''
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Pedidos Calkiní — Tu'ux</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
                background: #f5f5f5;
            }

            h1 {
                margin-bottom: 10px;
            }

            .pedido {
                background: white;
                padding: 18px;
                margin-bottom: 15px;
                border-radius: 10px;
                box-shadow: 0 2px 8px rgba(0,0,0,.08);
            }

            .dato {
                margin: 5px 0;
            }

            .estado {
                font-weight: bold;
            }

            select, button {
                padding: 10px;
                margin-top: 8px;
                font-size: 16px;
            }

            button {
                cursor: pointer;
            }

            .comparacion {
                margin-top: 10px;
                padding: 8px;
                background: #f0f0f0;
                border-radius: 6px;
            }
        </style>
    </head>

    <body>

        <h1>📦 Pedidos Calkiní</h1>
        <p>Registro interno del espacio físico utilizado.</p>
    '''

    if not pedidos:
        html += '<p>No hay pedidos Calkiní registrados.</p>'

    # ==========================================
    # 5B.5D-3B.3 — RESUMEN DE APRENDIZAJE
    # ==========================================

    total_pedidos = len(pedidos)
    pedidos_evaluados = 0
    correctos = 0
    diferencias = 0
    subestimaciones = 0
    sobreestimaciones = 0
    cobertura_evaluacion = 0
    precision_actual = 0
    pedidos_pendientes = 0
    transiciones = {}
    resultados_tamano = {}

    for pedido in pedidos:
        estimated = (pedido['logistics_estimated_space'] or '').strip().upper()
        actual = (pedido['logistics_actual_space'] or '').strip().upper()
        
        if actual in ('CHICO', 'MEDIANO', 'GRANDE'):
            pedidos_evaluados += 1
            transicion = f"{estimated} → {actual}"
            resultados_tamano[transicion] = resultados_tamano.get(transicion, 0) + 1

            if estimated == actual:
                correctos += 1

            elif (
                estimated in LOGISTICS_SIZE_ORDER
                and actual in LOGISTICS_SIZE_ORDER
            ):
                diferencias += 1

                transicion = f"{estimated} → {actual}"
                transiciones[transicion] = transiciones.get(transicion, 0) + 1

                if LOGISTICS_SIZE_ORDER[estimated] < LOGISTICS_SIZE_ORDER[actual]:
                    subestimaciones += 1
                elif LOGISTICS_SIZE_ORDER[estimated] > LOGISTICS_SIZE_ORDER[actual]:
                    sobreestimaciones += 1

    if total_pedidos > 0:
        cobertura_evaluacion = (pedidos_evaluados / total_pedidos) * 100

    if pedidos_evaluados > 0:
        precision_actual = (correctos / pedidos_evaluados) * 100

    pedidos_pendientes = total_pedidos - pedidos_evaluados
    
    html += f'''
    <div class="pedido">
        <h2>📊 Resumen de aprendizaje</h2>

        <div class="dato">
            <strong>Pedidos Calkiní:</strong> {total_pedidos}
        </div>

        <div class="dato">
            <strong>Pedidos evaluados:</strong> {pedidos_evaluados}

        <div class="dato">
            <strong>Pedidos pendientes de evaluar:</strong> {pedidos_pendientes}
        </div>
        
        </div>

        <div class="dato">
            <strong>Cobertura de evaluación:</strong> {cobertura_evaluacion:.1f}%
        </div>

        <div class="dato">
            <strong>Precisión actual:</strong> {precision_actual:.1f}%
        </div>

        <div class="dato">
            <strong>Estimaciones correctas:</strong> {correctos}
        </div>

        <div class="dato">
            <strong>Se quedó corto:</strong> {subestimaciones}
        </div>

        <div class="dato">
            <strong>Se pasó:</strong> {sobreestimaciones}
        </div>

        <div class="dato">
            <strong>Resultados evaluados:</strong>
        </div>
'''
    if resultados_tamano:
        for resultado, cantidad in sorted(resultados_tamano.items()):
            html += f'''
            <div class="dato">
                {resultado}: <strong>{cantidad}</strong>
            </div>
            '''
    else:
        html += '''
        <div class="dato">
            Ninguno todavía.
        </div>
        '''

    html += '''
        <div class="dato">
            <strong>Detalle de diferencias:</strong>
        </div>
'''
    if transiciones:
        for transicion, cantidad in sorted(transiciones.items()):
            html += f'''
            <div class="dato">
                {transicion}: <strong>{cantidad}</strong>
            </div>
            '''
    else:
        html += '''
        <div class="dato">
            Ninguna todavía.
        </div>
        '''
    html += '''
        </div>
    '''


    for pedido in pedidos:

        pedido_id = pedido['id']
        estimated = pedido['logistics_estimated_space'] or 'SIN ESTIMAR'
        actual = pedido['logistics_actual_space'] or 'PENDIENTE'
        status = pedido['logistics_status'] or 'SIN ESTADO'

        # Obtener productos del pedido para revisión interna
        try:
            with proyecto._connect() as conn_items:
                cursor_items = conn_items.cursor()

                cursor_items.execute('''
                    SELECT
                        pi.unidades,
                        pi.precio,
                        pi.logistics_size,
                        p.nombre
                    FROM pedido_items pi
                    JOIN productos p ON p.id = pi.producto_id
                    WHERE pi.pedido_id = ?
                ''', (pedido_id,))

                items_pedido = cursor_items.fetchall()

        except Exception as e:
            print('ERROR CARGANDO ITEMS PEDIDO CALKINÍ:', e)
            items_pedido = []

        html += f'''
        <div class="pedido">

            <h2>Pedido #{pedido_id}</h2>

            <div class="dato">
                <strong>Fecha:</strong> {pedido['created_at']}
            </div>

            <div class="dato">
                <strong>Productos:</strong>
                <ul>
        '''

        for item in items_pedido:
            nombre = item['nombre'] or 'Producto'
            unidades = item['unidades'] or 0
            logistics_size = item['logistics_size'] or 'SIN CLASIFICAR'

            html += f'''
                    <li>
                        {nombre} × {unidades}
                        — {logistics_size}
                    </li>
            '''

        html += f'''
                </ul>
            </div>

            <div class="dato">
                <strong>Total:</strong> ${pedido['total']:.2f}
            </div>

            <div class="dato">
                <strong>Envío inicial:</strong> ${pedido['shipping_initial']:.2f}
            </div>

            <div class="dato">
                <strong>Estimación:</strong> {estimated}
            </div>

            <div class="dato">
                <strong>Espacio real:</strong> {actual}
            </div>

            <div class="dato estado">
                Estado: {status}
            </div>
        '''

        if actual != 'PENDIENTE':
            if estimated == actual:
                resultado = '✅ CORRECTO'
            else:
                resultado = '⚠️ DIFERENCIA'
            html += f'''
            <div class="comparacion">
                📊 Comparación:
                <strong>Estimado {estimated}</strong>
                → <strong>Real {actual}</strong>
                <br>
                <strong>{resultado}</strong>
            </div>
        '''

        html += f'''
            <form method="POST">

                <input
                    type="hidden"
                    name="pedido_id"
                    value="{pedido_id}"
                >

                <label>
                    <strong>Registrar espacio real:</strong>
                </label>

                <br>

                <select name="actual_space" required>
                    <option value="">Seleccionar...</option>
                    <option value="CHICO">CHICO</option>
                    <option value="MEDIANO">MEDIANO</option>
                    <option value="GRANDE">GRANDE</option>
                </select>

                <br>

                <button type="submit">
                    Guardar espacio real
                </button>

            </form>

        </div>
        '''

    html += '''
    </body>
    </html>
    '''

    return html

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        tipo_usuario = request.form.get('tipo_usuario', 'cliente')
        username = request.form['username'].strip()
        password = request.form['password']
        password2 = request.form['password2']
        if password != password2:
            flash('Las contraseñas no coinciden.')
            return redirect(url_for('register'))
        ok, message = create_account(username, password, tipo_usuario)
        flash(message)
        if ok:
            session['username'] = username
            session['tipo_usuario'] = tipo_usuario
            if tipo_usuario == 'vendedor':
                return redirect(url_for('businesspeople'))
            return redirect(url_for('market'))
    return render_template('register.html')

@app.route('/registrar-tienda-proveedor', methods=['POST'])
def registrar_tienda_proveedor():

    if not session.get('username'):
        return redirect(url_for('login'))

    if session.get('tipo_usuario') != 'vendedor':
        flash('Acceso restringido a vendedores.')
        return redirect(url_for('market'))

    nombre_tienda = request.form.get('nombre_tienda', '').strip()
    codigo_postal = request.form.get('codigo_postal', '').strip()

    if not nombre_tienda:
        flash('Ingresa el nombre de la tienda.')
        return redirect(url_for('businesspeople'))

    if not codigo_postal.isdigit() or len(codigo_postal) != 5:
        flash('El código postal debe tener 5 dígitos.')
        return redirect(url_for('businesspeople'))

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        # Usamos el primer mercado existente como mercado de la tienda
        cursor.execute('''
            SELECT id
            FROM mercados
            ORDER BY id ASC
            LIMIT 1
        ''')

        mercado = cursor.fetchone()

        if not mercado:
            conn.close()
            flash('No existe ningún mercado registrado.')
            return redirect(url_for('businesspeople'))

        mercado_id = mercado['id']

        tienda = proyecto.Tienda(
            nombre_tienda,
            '',
            '',
            'proveedor',
            codigo_postal
        )

        tienda_id = proyecto.save_tienda(
            tienda,
            mercado_id,
            session.get('username')
        )
        conn.close()

        print(
            "TIENDA REGISTRADA:",
            nombre_tienda,
            "| CP:",
            codigo_postal,
            "| ID:",
            tienda_id
        )

        flash(f'✅ Tienda "{nombre_tienda}" registrada correctamente.')

    except Exception as e:
        print('ERROR REGISTRANDO TIENDA:', e)
        flash(f'Error registrando la tienda: {e}')

    return redirect(url_for('businesspeople'))

@app.route('/businesspeople')
def businesspeople():
    if not session.get('username'):
        return redirect(url_for('login'))

    if session.get('tipo_usuario') != 'vendedor':
        flash('Acceso restringido a vendedores.')
        return redirect(url_for('market'))

    vendedor_username = session.get('username')
    print("VENDEDOR ACTUAL:", repr(vendedor_username))

    productos_vendedor = []
    tiendas = []

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        # Tiendas reales de la base de datos
        cursor.execute('''
            SELECT
                id,
                nombre,
                mercado_id
            FROM tiendas
            WHERE vendedor_username = ?
            ORDER BY id ASC
        ''', (vendedor_username,))
        
        tiendas = cursor.fetchall()

        print("TIENDAS ENCONTRADAS:", len(tiendas))
        print("TIENDAS:", tiendas)

        # Productos pertenecientes al vendedor actual
        cursor.execute('''
            SELECT
                id,
                tienda_id,
                nombre,
                unidades,
                precio,
                presentacion,
                imagen
            FROM productos
            WHERE vendedor_username = ?
            ORDER BY id DESC
        ''', (vendedor_username,))

        productos_vendedor = cursor.fetchall()

        print("PRODUCTOS ENCONTRADOS:", len(productos_vendedor))
        print("PRODUCTOS:", productos_vendedor)

        conn.close()

    except Exception as e:
        print('ERROR CARGANDO DATOS DEL PROVEEDOR:', e)

    return render_template(
        'businesspeople.html',
        tiendas=tiendas,
        productos_vendedor=productos_vendedor
    )

@app.route('/proveedor/agregar-producto', methods=['POST'])
def agregar_producto_proveedor():

    if not session.get('username'):
        return redirect(url_for('login'))

    if session.get('tipo_usuario') != 'vendedor':
        flash('Acceso restringido a vendedores.')
        return redirect(url_for('market'))

    vendedor_username = session.get('username')

    # Obtener datos del formulario
    tienda_id = request.form.get('tienda_id', '').strip()
    
    print("DEBUG tienda_id RECIBIDO:", tienda_id)
    print("DEBUG formulario:", request.form.to_dict())
    
    nombre = request.form.get('nombre', '').strip()
    presentacion = request.form.get('presentacion', '').strip()    
    precio = request.form.get('precio', '').strip()
    unidades = request.form.get('unidades', '').strip()
    logistics_size = request.form.get('logistics_size', '').strip().upper()
    categoria = request.form.get('categoria', '').strip().upper()

    # Validar campos obligatorios
    if not tienda_id or not nombre or not presentacion or not precio or not unidades:
        flash('Completa todos los campos obligatorios.')
        return redirect(url_for('businesspeople'))

    # Convertir tipos
    try:
        tienda_id = int(tienda_id)
        
        # Precio que el proveedor quiere recibir
        precio_proveedor = float(precio)

        # Precio público de TU'UX (+20%)
        precio = round(precio_proveedor * 1.20, 2)

        unidades = int(unidades)
        
    except ValueError:
        flash('Precio o stock inválido.')
        return redirect(url_for('businesspeople'))

    # Validar valores
    if tienda_id <= 0:
        flash('Tienda no válida.')
        return redirect(url_for('businesspeople'))

    if precio < 0 or unidades < 0:
        flash('El precio y el stock no pueden ser negativos.')
        return redirect(url_for('businesspeople'))

    # Verificar que la tienda exista REALMENTE en SQLite
    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, nombre
            FROM tiendas
            WHERE id = ?
              AND vendedor_username = ?
        ''', (tienda_id, vendedor_username))

        tienda_row = cursor.fetchone()

        conn.close()

        if not tienda_row:
            flash('La tienda seleccionada no existe.')
            return redirect(url_for('businesspeople'))

        print(
            "TIENDA SELECCIONADA:",
            tienda_row['id'],
            tienda_row['nombre']
        )

    except Exception as e:
        print('ERROR VERIFICANDO TIENDA:', e)
        flash('No se pudo verificar la tienda.')
        return redirect(url_for('businesspeople'))

    # Procesar imagen
    imagen_nombre = None

    archivo = request.files.get('imagen')

    if archivo and archivo.filename:
        nombre_archivo = archivo.filename.replace(' ', '_')

        os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)
        
        ruta_imagen = os.path.join(
            PRODUCT_IMAGES_DIR,
            nombre_archivo
        )
        
        archivo.save(ruta_imagen)
        
        imagen_nombre = nombre_archivo

    # Crear producto
    producto = proyecto.Producto(
        nombre,
        unidades,
        precio,
        presentacion,
        imagen_nombre
    )

    # Guardar directamente en SQLite usando el ID REAL de la tienda
    try:
        proyecto.save_producto(
            producto,
            tienda_id,
            vendedor_username,
            precio_proveedor,
            logistics_size,
            categoria
        )

        print(
            "PRODUCTO GUARDADO:",
            nombre,
            "| tienda_id:",
            tienda_id,
            "| vendedor:",
            vendedor_username
        )

    except Exception as e:
        print('ERROR GUARDANDO PRODUCTO EN DB:', e)
        flash(f'Error guardando producto en DB: {e}')
        return redirect(url_for('businesspeople'))

    flash(f'✅ {nombre} fue agregado correctamente al catálogo.')
    return redirect(url_for('businesspeople'))


@app.route('/proveedor/editar-producto/<int:producto_id>', methods=['GET', 'POST'])
def editar_producto_proveedor(producto_id):

    if not session.get('username'):
        return redirect(url_for('login'))

    if session.get('tipo_usuario') != 'vendedor':
        flash('Acceso restringido a vendedores.')
        return redirect(url_for('market'))

    vendedor_username = session.get('username')

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        # Buscar únicamente un producto que pertenezca al vendedor
        cursor.execute('''
            SELECT
                id, 
                nombre, 
                unidades, 
                precio, 
                presentacion, 
                imagen, 
                logistics_size,
                categoria
            FROM productos
            WHERE id = ?
              AND vendedor_username = ?
        ''', (producto_id, vendedor_username))

        producto = cursor.fetchone()

        if not producto:
            conn.close()
            flash('Producto no encontrado.')
            return redirect(url_for('businesspeople'))

        if request.method == 'POST':

            nombre = request.form.get('nombre', '').strip()
            presentacion = request.form.get('presentacion', '').strip()
            precio = request.form.get('precio', 0)
            unidades = request.form.get('unidades', 0)
            logistics_size = request.form.get('logistics_size', '').strip().upper()
            categoria = request.form.get('categoria', '').strip().upper()

            cursor.execute('''
                UPDATE productos
                SET nombre = ?,
                    presentacion = ?,
                    precio = ?,
                    unidades = ?,
                    logistics_size = ?,
                    categoria = ?
                WHERE id = ?
                    AND vendedor_username = ?
            ''', (
                nombre,
                presentacion,
                float(precio),
                int(unidades),
                logistics_size,
                categoria,
                producto_id,
                vendedor_username
                
            ))

            conn.commit()
            conn.close()

            flash('Producto actualizado correctamente.')
            return redirect(url_for('businesspeople'))

        conn.close()

        return render_template(
            'editar_producto.html',
            producto=producto
        )

    except Exception as e:
        print('ERROR EDITANDO PRODUCTO:', e)
        flash(f'Error editando producto: {e}')
        return redirect(url_for('businesspeople'))

@app.route('/proveedor/agotar-producto/<int:producto_id>', methods=['POST'])
def agotar_producto_proveedor(producto_id):

    if not session.get('username'):
        return redirect(url_for('login'))

    if session.get('tipo_usuario') != 'vendedor':
        flash('Acceso restringido a vendedores.')
        return redirect(url_for('market'))

    vendedor_username = session.get('username')

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE productos
            SET unidades = 0
            WHERE id = ?
              AND vendedor_username = ?
        ''', (producto_id, vendedor_username))

        conn.commit()
        conn.close()

        flash('Producto marcado como agotado.')

    except Exception as e:
        print('ERROR AGOTANDO PRODUCTO:', e)
        flash(f'Error agotando producto: {e}')

    return redirect(url_for('businesspeople'))


@app.route('/proveedor/activar-producto/<int:producto_id>', methods=['POST'])
def activar_producto_proveedor(producto_id):

    if not session.get('username'):
        return redirect(url_for('login'))

    if session.get('tipo_usuario') != 'vendedor':
        flash('Acceso restringido a vendedores.')
        return redirect(url_for('market'))

    vendedor_username = session.get('username')

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        # Por ahora ponemos 1 unidad al volver a activar.
        cursor.execute('''
            UPDATE productos
            SET unidades = 1
            WHERE id = ?
              AND vendedor_username = ?
              AND unidades = 0
        ''', (producto_id, vendedor_username))

        conn.commit()
        conn.close()

        flash('Producto nuevamente disponible.')

    except Exception as e:
        print('ERROR ACTIVANDO PRODUCTO:', e)
        flash(f'Error activando producto: {e}')

    return redirect(url_for('businesspeople'))

@app.route('/proveedor/eliminar-producto/<int:producto_id>', methods=['POST'])
def eliminar_producto_proveedor(producto_id):

    if not session.get('username'):
        return redirect(url_for('login'))

    if session.get('tipo_usuario') != 'vendedor':
        flash('Acceso restringido a vendedores.')
        return redirect(url_for('market'))

    vendedor_username = session.get('username')

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM productos
            WHERE id = ?
              AND vendedor_username = ?
        ''', (producto_id, vendedor_username))

        conn.commit()
        conn.close()

        flash('Producto eliminado correctamente.')

    except Exception as e:
        print('ERROR ELIMINANDO PRODUCTO:', e)
        flash(f'Error eliminando producto: {e}')

    return redirect(url_for('businesspeople'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        
        password = request.form['password']
        ok, message = verify_login(username, password)
        flash(message)
        if ok:
            session['username'] = username
            user_role = (get_user_role(username) or 'cliente').lower()
            session['tipo_usuario'] = user_role
            if user_role == 'vendedor':
                return redirect(url_for('businesspeople'))
            return redirect(url_for('market'))
    return render_template('login.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username'].strip()
        ok, token_or_msg = create_reset_token(username)
        if not ok:
            flash(token_or_msg)
            return redirect(url_for('forgot_password'))
        session['password_reset_username'] = username
        session['password_reset_token'] = token_or_msg
        flash('Se generó un código de recuperación. Ahora ingresa un nuevo password.')
        return redirect(url_for('reset_password'))
    return render_template('forgot_password.html')


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    username = session.get('password_reset_username', '')
    token = session.get('password_reset_token', '')
    if request.method == 'POST':
        username = request.form['username'].strip()
        token = request.form['token'].strip()
        password = request.form['password']
        password2 = request.form['password2']
        if password != password2:
            flash('Las contraseñas no coinciden.')
            return redirect(url_for('reset_password'))
        ok, message = reset_user_password(username, password, token)
        flash(message)
        if ok:
            session.pop('password_reset_token', None)
            session.pop('password_reset_username', None)
            return redirect(url_for('login'))
    return render_template('reset_password.html', username=username, token=token)


@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('tipo_usuario', None)
    flash('Sesión cerrada correctamente. El carrito se mantendrá en esta sesión.')
    return redirect(url_for('index'))


@app.route('/market_request', methods=['POST'])
def market_request():
    wants_json = request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    nombre = request.form.get('nombre', '').strip()
    celular = request.form.get('celular', '').strip()
    municipio = request.form.get('municipio', '').strip()
    tienda = request.form.get('tienda', '').strip()
    direccion = request.form.get('direccion', '').strip()
    producto = request.form.get('producto', '').strip()
    cantidad = request.form.get('cantidad', '1').strip()
    detalles = request.form.get('detalles', '').strip()
    if not nombre or not celular or not municipio or not tienda or not direccion or not producto:
        message = 'Ingresa los datos requeridos en los siguientes campos.'
        if wants_json:
            return jsonify({'ok': False, 'error': message}), 400
        flash(message)
        return redirect(url_for('marketlist'))
    if not cantidad.isdigit() or int(cantidad) <= 0:
        message = 'Cantidad inválida.'
        if wants_json:
            return jsonify({'ok': True})        
        flash(message)
        return redirect(url_for('marketlist'))
    
    cart = get_cart()
    if cart:
        # Extraemos el nombre de la tienda del primer artículo que ya esté en el carrito
        # (Usamos .get por si la llave se llama 'tienda' o 'store_name')
        primera_tienda = cart[0].get('tienda' or 'store_name', '').strip().lower()
        
        if tienda.lower() != primera_tienda:
            message = f"Atención! Confirma tu pedido por WhatsApp y pregunta por disponibilidad para el servicio de otra tienda"
            if wants_json:
                return jsonify({'ok': False, 'error': message}), 400
            flash(message)
            return redirect(url_for('marketlist'))
            
    cart.append({
        'custom': True,
        'tienda': tienda,
        'direccion': direccion,
        'producto': producto,
        'cantidad': int(cantidad),
        'detalles': detalles,
    })
    save_cart(cart)
    # Guardar datos básicos del pedido personalizado para el mensaje y la recarga del formulario
    market_request = {
        'nombre': nombre,
        'celular': celular,
        'municipio': municipio,
        'tienda': tienda,
        'direccion': direccion,
        'producto': '',
        'cantidad': 1,
        'detalles': '',
    }
    session['market_request'] = market_request
    if not wants_json:
        flash('Pedido agregado al carrito.')
        
    items, total = build_cart_items()
    total += calculate_store_switch_fee(get_cart())
    if request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'ok': True,
            'cart_total': total,
            'cart_count': len(get_cart()),
        })

    return redirect(url_for('marketlist'))

@app.route('/market-list')
def marketlist():
    market_request_data = session.get('market_request', None)

    cart_store_keys = get_cart_store_keys()

    items, total = build_cart_items()
    total += calculate_store_switch_fee(get_cart())

    step = request.args.get('step', 1, type=int)

    return render_template(
        'marketlist.html',
        market_request=market_request_data,
        cart_store_keys=cart_store_keys,
        initial_step=step,
        cart_total=total
    )

@app.route('/market')
def market():
    productos = []

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        categoria = request.args.get('categoria', '').strip().upper()

        if categoria == 'OTROS':
            cursor.execute('''
                SELECT
                    p.id AS producto_id,
                    p.tienda_id,
                    p.nombre,
                    p.unidades,
                    p.precio,
                    p.presentacion,
                    p.imagen,
                    p.vendedor_username,
                    t.nombre AS tienda_nombre
                FROM productos p
                LEFT JOIN tiendas t ON p.tienda_id = t.id
                WHERE p.categoria = 'OTROS'
                   OR p.categoria IS NULL
                   OR TRIM(p.categoria) = ''
                ORDER BY p.id DESC
            ''')

        elif categoria in ('MOCHILAS', 'BOLSAS', 'CUIDADO_PERSONAL'):
            cursor.execute('''
                SELECT
                    p.id AS producto_id,
                    p.tienda_id,
                    p.nombre,
                    p.unidades,
                    p.precio,
                    p.presentacion,
                    p.imagen,
                    p.vendedor_username,
                    t.nombre AS tienda_nombre
                FROM productos p
                LEFT JOIN tiendas t ON p.tienda_id = t.id
                WHERE p.categoria = ?
                ORDER BY p.id DESC
            ''', (categoria,))

        else:
            cursor.execute('''
                SELECT
                    p.id AS producto_id,
                    p.tienda_id,
                    p.nombre,
                    p.unidades,
                    p.precio,
                    p.presentacion,
                    p.imagen,
                    p.vendedor_username,
                    t.nombre AS tienda_nombre
                FROM productos p
                LEFT JOIN tiendas t ON p.tienda_id = t.id
                ORDER BY p.id DESC
            ''')

        productos = cursor.fetchall()
        conn.close()

    except Exception as e:
        print('ERROR CARGANDO PRODUCTOS DEL MARKET:', e)

    return render_template(
        'market.html',
        productos=productos,
        market_request=session.get('market_request')
    )

@app.route('/producto/<int:store_id>/<int:product_id>')
def detalle_producto(store_id, product_id):

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                p.id,
                p.tienda_id,
                p.nombre,
                p.unidades,
                p.precio,
                p.presentacion,
                p.imagen,
                t.nombre AS tienda_nombre
            FROM productos p
            LEFT JOIN tiendas t ON p.tienda_id = t.id
            WHERE p.id = ?
              AND p.tienda_id = ?
        ''', (product_id, store_id))

        producto = cursor.fetchone()
        conn.close()

        if not producto:
            flash('Producto no encontrado.')
            return redirect(url_for('market'))

        return render_template(
            'producto.html',
            tienda=producto['tienda_nombre'],
            producto=producto,
            store_id=store_id,
            product_id=product_id
        )

    except Exception as e:
        print('ERROR CARGANDO DETALLE DEL PRODUCTO:', e)
        flash('No se pudo cargar el producto.')
        return redirect(url_for('market'))

@app.route('/add/<int:store_id>/<int:product_id>', methods=['POST'])
def add_to_cart(store_id, product_id):

    try:
        conn = proyecto._connect()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                id,
                tienda_id,
                nombre,
                unidades,
                precio,
                presentacion,
                imagen,
                logistics_size
            FROM productos
            WHERE id = ?
              AND tienda_id = ?
        ''', (product_id, store_id))

        producto = cursor.fetchone()
        conn.close()

    except Exception as e:
        print('ERROR BUSCANDO PRODUCTO PARA CARRITO:', e)
        flash('No se pudo encontrar el producto.')
        return redirect(url_for('market'))

    if not producto:
        flash('Producto no encontrado.')
        return redirect(url_for('market'))

    cantidad = request.form.get('cantidad', '1')

    if not cantidad.isdigit() or int(cantidad) <= 0:
        flash('Cantidad inválida.')
        return redirect(
            url_for(
                'detalle_producto',
                store_id=store_id,
                product_id=product_id
            )
        )

    cantidad = int(cantidad)

    if cantidad > producto['unidades']:
        flash('Stock insuficiente.')
        return redirect(
            url_for(
                'detalle_producto',
                store_id=store_id,
                product_id=product_id
            )
        )

    cart = get_cart()

    alerta_tienda = None

    existing_store_ids = {
        item.get('store_id')
        for item in cart
        if item.get('store_id') is not None
    }

    if existing_store_ids and store_id not in existing_store_ids:
        alerta_tienda = '¿Deseas agregar otra tienda por $50 y sumarlo al total?'
        flash(alerta_tienda)

    producto_existente = None

    for item in cart:
        if (
            not item.get('custom')
            and item.get('store_id') == store_id
            and item.get('product_id') == product_id
        ):
            producto_existente = item
            break

    if producto_existente:

        nueva_cantidad = producto_existente.get('cantidad', 0) + cantidad

        if nueva_cantidad > producto['unidades']:
            flash('La cantidad total supera el stock disponible.')
            return redirect(
                url_for(
                    'detalle_producto',
                    store_id=store_id,
                    product_id=product_id
                )
            )

        producto_existente['cantidad'] = nueva_cantidad

    else:

        cart.append({
            'custom': False,
            'store_id': store_id,
            'product_id': product_id,
            'cantidad': cantidad,
            'producto': {
                'nombre': producto['nombre'],
                'precio': producto['precio'],
                'presentacion': producto['presentacion'],
                'imagen': producto['imagen'],
                'unidades': producto['unidades'],
                'logistics_size': producto['logistics_size']
            }
        })

    save_cart(cart)
    
    print("=== DEBUG CARRITO ===")
    print(cart)
    print("=== FIN DEBUG ===")

    # La confirmación se muestra directamente en la página mediante AJAX.
    
    total_piezas = sum(
        int(item.get('cantidad', 1))
        for item in cart
    )

    if (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.accept_json
    ):
        return jsonify({
            'ok': True,
            'cart_count': total_piezas,
            'alerta_tienda': alerta_tienda
        })

    return redirect(
        url_for(
            'detalle_producto',
            store_id=store_id,
            product_id=product_id
        )
    )


@app.route('/cart')
def cart():
    items, product_total = build_cart_items()
    cart_items = get_cart()
    switch_fee = calculate_store_switch_fee(cart_items)
    total = product_total + switch_fee
    tiene_custom = any(item.get('custom') for item in cart_items)

    grouped_items = {}
    for item in items:
        if item.get('custom'):
            tienda_nombre = item.get('tienda') or 'Tienda personalizada'
        else:
            tienda_obj = item.get('tienda')
            tienda_nombre = getattr(tienda_obj, 'nombre', 'Tienda desconocida')
        grouped_items.setdefault(tienda_nombre, []).append(item)

    grouped_items = dict(sorted(grouped_items.items(), key=lambda kv: kv[0].lower()))
    return render_template(
    'cart.html',
    grouped_items=grouped_items,
    total=total,
    product_total=product_total,
    tiene_custom=tiene_custom
)


@app.route('/checkout', methods=['POST'])
def checkout():
    # Recoger información del pedido desde el formulario
    tienda = request.form.get('tienda', '').strip()
    direccion = request.form.get('direccion', '').strip()
    producto_note = request.form.get('producto', '').strip()
    detalles = request.form.get('detalles', '').strip()

    # Tomar snapshot de los items y total antes de limpiar el carrito
    items_snapshot, total = build_cart_items()
    serializable_items = []
    for it in items_snapshot:
        serializable_items.append({
            'store_id': it.get('store_id'),
            'store_name': getattr(it.get('tienda'), 'nombre', None),
            'product_id': it.get('product_id'),
            'product_name': getattr(it.get('producto'), 'nombre', None),
            'presentacion': getattr(it.get('producto'), 'presentacion', None),
            'cantidad': it.get('cantidad'),
            'precio': getattr(it.get('producto'), 'precio', None),
            'subtotal': it.get('subtotal'),
        })

    # Guardar la información del pedido en la sesión (puedes cambiar a DB si prefieres)
    session['order_info'] = {
        'tienda': tienda,
        'direccion': direccion,
        'producto': producto_note,
        'detalles': detalles,
        'items': serializable_items,
        'total': total,
    }

    # Persistir pedido en la base de datos
    try:
        save_order_to_db(session['order_info'], session.get('username'))
    except Exception as e:
        # No fallamos la compra por error de persistencia, solo lo registramos
        print('Error guardando pedido en DB:', e)

    # Enviar email con el resumen del pedido
    try:
        send_order_email(session['order_info'])
    except Exception as e:
        print('Error enviando email:', e)

    # Limpiar carrito y confirmar pedido
    session['cart'] = []
    flash('Compra realizada correctamente. Gracias por tu pedido.')
    return redirect(url_for('order'))


@app.route('/order')
def order():
    order_info = session.get('order_info')
    # Obtener los items y total desde la orden si existen, si no usar el carrito actual
    if order_info and isinstance(order_info.get('items'), list):
        order_items = order_info.get('items')
        order_total = order_info.get('total', 0)
    else:
        order_items, order_total = build_cart_items()
    return render_template('order.html', order=order_info, items=order_items, total=order_total, order_items=order_items, order_total=order_total)


@app.route('/process-payment', methods=['POST'])
def process_payment():
    
    payment_method = request.form.get('payment_method', '').strip()
    payment_notes = request.form.get('payment_notes', '').strip()
    
    payment_data = {
        'method': payment_method,
        'notes': payment_notes,
        'timestamp': datetime.datetime.now().isoformat()
    }
    
    # TRANSFERENCIA BANCARIA
    if 'Transferencia' in payment_method:
        spei_number = request.form.get('spei_number', '').strip()
        bank_name = request.form.get('bank_name', '').strip()
        account_holder = request.form.get('account_holder', '').strip()
        
        if not spei_number or not bank_name or not account_holder:
            flash('Por favor completa todos los campos de transferencia bancaria.')
            return redirect(url_for('order'))
        
        payment_data.update({
            'spei_number': spei_number,
            'bank_name': bank_name,
            'account_holder': account_holder,
        })
        flash(f'✅ Pago por transferencia {bank_name} registrado. Número SPEI: {spei_number[:4]}****. Completaremos tu pedido una vez recibida la transferencia.')
    
    # TARJETA DE CRÉDITO
    elif 'crédito' in payment_method or 'credito' in payment_method:
        card_number = request.form.get('card_number', '').strip()
        cardholder_name = request.form.get('cardholder_name', '').strip()
        expiry_date = request.form.get('expiry_date', '').strip()
        cvv = request.form.get('cvv', '').strip()
        
        if not card_number or not cardholder_name or not expiry_date or not cvv:
            flash('Por favor completa todos los campos de tarjeta de crédito.')
            return redirect(url_for('order'))
        
        payment_data.update({
            'card_number': card_number[-4:],  # Solo guardar últimos 4 dígitos
            'cardholder_name': cardholder_name,
            'expiry_date': expiry_date,
        })
        flash(f'✅ Tarjeta de crédito registrada ({card_number[-4:]}). ¡Gracias por tu compra!')
    
    # TARJETA DE DÉBITO
    elif 'débito' in payment_method or 'debito' in payment_method:
        debit_card_number = request.form.get('debit_card_number', '').strip()
        debit_holder_name = request.form.get('debit_holder_name', '').strip()
        debit_expiry_date = request.form.get('debit_expiry_date', '').strip()
        debit_cvv = request.form.get('debit_cvv', '').strip()
        
        if not debit_card_number or not debit_holder_name or not debit_expiry_date or not debit_cvv:
            flash('Por favor completa todos los campos de tarjeta de débito.')
            return redirect(url_for('order'))
        
        payment_data.update({
            'card_number': debit_card_number[-4:],  # Solo guardar últimos 4 dígitos
            'cardholder_name': debit_holder_name,
            'expiry_date': debit_expiry_date,
        })
        flash(f'✅ Tarjeta de débito registrada ({debit_card_number[-4:]}). ¡Gracias por tu compra!')
    
    # EFECTIVO
    elif 'Efectivo' in payment_method:
        cash_amount = request.form.get('cash_amount', '').strip()
        
        try:
            cash_value = float(cash_amount)
            if cash_value <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            flash('Por favor ingresa un monto válido.')
            return redirect(url_for('order'))
        
        payment_data.update({
            'cash_amount': cash_value,
        })
        flash(f'✅ Pago en efectivo registrado (${cash_amount}). El repartidor confirmará el cambio en la entrega.')
    
    # BILLETERA VIRTUAL
    elif 'Billetera' in payment_method or 'virtual' in payment_method:
        wallet_type = request.form.get('wallet_type', '').strip()
        wallet_username = request.form.get('wallet_username', '').strip()
        wallet_phone = request.form.get('wallet_phone', '').strip()
        
        if not wallet_type or not wallet_username:
            flash('Por favor completa los campos requeridos de billetera virtual.')
            return redirect(url_for('order'))
        
        payment_data.update({
            'wallet_type': wallet_type,
            'wallet_username': wallet_username,
            'wallet_phone': wallet_phone,
        })
        flash(f'✅ Billetera virtual {wallet_type.upper()} registrada. ¡Gracias por tu compra!')
    
    else:
        flash('Método de pago no válido.')
        return redirect(url_for('order'))
    
    # Guardar información del pago en la sesión
    session['payment_info'] = payment_data
    
    # Opcional: guardar el pago en la BD asociado con la orden
    try:
        save_payment_to_db(session.get('username'), session.get('order_info', {}), payment_data)
    except Exception as e:
        print(f'Error guardando información de pago: {e}')
    
    return redirect(url_for('market'))


@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.svg'))

@app.context_processor
def cart_counter():
    carrito = session.get("cart", [])
    total_piezas = sum(int(item.get('cantidad', 1)) for item in carrito)
    return dict(cart_count=total_piezas)
    
def ensure_order_tables():
    conn = proyecto._connect()
    with conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS orders_text (
            id INTEGER PRIMARY KEY, username TEXT, tienda TEXT, direccion TEXT,
            producto_note TEXT, detalles TEXT, total REAL, created_at TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS order_items_text (
            id INTEGER PRIMARY KEY, order_id INTEGER, store_name TEXT, product_name TEXT,
            presentacion TEXT, cantidad INTEGER, precio REAL, subtotal REAL,
            FOREIGN KEY(order_id) REFERENCES orders_text(id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS payment_info (
            id INTEGER PRIMARY KEY, username TEXT, order_id INTEGER, payment_method TEXT,
            payment_data TEXT, notes TEXT, created_at TEXT,
            FOREIGN KEY(order_id) REFERENCES orders_text(id)
        )''')
    conn.close()


def save_payment_to_db(username, order_info, payment_data):
    """Guarda la información de pago en la base de datos."""
    ensure_order_tables()
    conn = proyecto._connect()
    try:
        with conn:
            c = conn.cursor()
            created_at = datetime.datetime.utcnow().isoformat()
            
            # Intentar obtener el último order_id del usuario
            c.execute('SELECT id FROM orders_text WHERE username = ? ORDER BY id DESC LIMIT 1', (username,))
            result = c.fetchone()
            order_id = result[0] if result else None
            
            # Convertir payment_data a string JSON para guardar
            payment_data_json = json.dumps(payment_data)
            
            c.execute('''INSERT INTO payment_info (username, order_id, payment_method, payment_data, notes, created_at)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (username, order_id, payment_data.get('method'), payment_data_json, 
                       payment_data.get('notes', ''), created_at))
    finally:
        conn.close()


def save_order_to_db(order_info, username=None):
    # Asegurar tablas
    ensure_order_tables()
    conn = proyecto._connect()
    with conn:
        c = conn.cursor()
        created_at = datetime.datetime.utcnow().isoformat()
        c.execute('INSERT INTO orders_text (username, tienda, direccion, producto_note, detalles, total, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (username, order_info.get('tienda'), order_info.get('direccion'), order_info.get('producto'), order_info.get('detalles'), order_info.get('total'), created_at))
        order_id = c.lastrowid
        for item in order_info.get('items', []):
            c.execute('INSERT INTO order_items_text (order_id, store_name, product_name, presentacion, cantidad, precio, subtotal) VALUES (?, ?, ?, ?, ?, ?, ?)',
                      (order_id, item.get('store_name'), item.get('product_name'), item.get('presentacion'), item.get('cantidad'), item.get('precio'), item.get('subtotal')))
    conn.close()


def send_order_email(order_info, recipient_email='faac_clocks@hotmail.com'):
    """Envía un email con el listado del carrito/pedido."""
    try:
        # Configurar SMTP (Gmail u otro proveedor)
        smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.environ.get('SMTP_PORT', 587))
        sender_email = os.environ.get('SENDER_EMAIL', 'tu_email@gmail.com')
        sender_password = os.environ.get('SENDER_PASSWORD', 'tu_contraseña')

        # Construir contenido del email
        subject = 'Resumen de tu pedido'
        
        body_html = '<html><body>'
        body_html += '<h2>Resumen de tu Pedido</h2>'
        body_html += f'<p><strong>Total:</strong> ${order_info.get("total", 0):.2f}</p>'
        body_html += '<table border="1" cellpadding="10" style="border-collapse: collapse;">'
        body_html += '<tr><th>Tienda</th><th>Producto</th><th>Presentación</th><th>Cantidad</th><th>Precio</th><th>Subtotal</th></tr>'
        
        for item in order_info.get('items', []):
            body_html += f'<tr>'
            body_html += f'<td>{item.get("store_name", "N/A")}</td>'
            body_html += f'<td>{item.get("product_name", "N/A")}</td>'
            body_html += f'<td>{item.get("presentacion", "N/A")}</td>'
            body_html += f'<td>{item.get("cantidad", 0)}</td>'
            body_html += f'<td>${item.get("precio", 0):.2f}</td>'
            body_html += f'<td>${item.get("subtotal", 0):.2f}</td>'
            body_html += f'</tr>'
        
        body_html += '</table>'
        body_html += f'<p><strong>Dirección de entrega:</strong> {order_info.get("direccion", "N/A")}</p>'
        body_html += f'<p><strong>Detalles:</strong> {order_info.get("detalles", "N/A")}</p>'
        body_html += '</body></html>'

        # Crear mensaje
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        # Enviar email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        
        print(f'Email enviado a {recipient_email}')
        return True
    except Exception as e:
        print(f'Error enviando email: {e}')
        return False


if __name__ == '__main__':
    # Escuchar en todas las interfaces para permitir acceso desde la red local
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', debug=True, port=port)
