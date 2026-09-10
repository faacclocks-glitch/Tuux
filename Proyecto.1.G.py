import os
import sys
import sqlite3
import datetime

# Permitir importar el módulo user_account desde el directorio padre
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from user_account import init_db as init_user_db, create_account_interactive, login_interactive

# ==========================================
# 1. MODELOS DE ENTIDADES (POO)
# ==========================================

class Producto:
    def __init__(self, nombre, unidades, precio, presentacion, imagen=None):
        self.nombre = nombre
        self.unidades = unidades  # Representa el Stock disponible
        self.precio = precio
        self.presentacion = presentacion
        self.imagen = imagen
    
    def mostrar_informacion(self):
        print(f"Producto: {self.nombre}, Stock: {self.unidades}, Precio: ${self.precio}, Presentación: {self.presentacion}")


class Tienda:
    def __init__(self, nombre, direccion, celular, giro, codigo_postal=None):
        self.nombre = nombre
        self.direccion = direccion
        self.celular = celular
        self.giro = giro
        self.codigo_postal = codigo_postal
        self.productos = []

    def agregar_producto(self, producto):
        self.productos.append(producto)

    def mostrar_productos(self):
        print(f"Productos disponibles en la tienda {self.nombre}:")
        for producto in self.productos:
            producto.mostrar_informacion()


class Mercado:
    def __init__(self, nombre, direccion, celular, email):
        self.nombre = nombre
        self.direccion = direccion
        self.celular = celular
        self.email = email
        self.tiendas = []
        self.usuarios = []
        self.premios = []
    
    def agregar_tienda(self, tienda):
        self.tiendas.append(tienda) 

    def mostrar_tiendas(self):
        print(f"Tiendas disponibles en {self.nombre}:")
        for tienda in self.tiendas:
            print(f"- {tienda.nombre} ({tienda.giro})") 
    
    def mostrar_productos(self):
        print(f"Todos los productos en {self.nombre}:")
        for tienda in self.tiendas:
            print(f"--- Tienda: {tienda.nombre} ---")
            for producto in tienda.productos:
                producto.mostrar_informacion()  


class Carrito:
    def __init__(self):
        # Guardaremos los productos como un diccionario: {Producto: cantidad}
        self.items = {}
    
    def agregar_producto(self, producto, cantidad=1):
        if producto in self.items:
            self.items[producto] += cantidad
        else:
            self.items[producto] = cantidad
    
    def borrar_productos(self, producto):
        if producto in self.items:
            del self.items[producto]
    
    def mostrar_carrito(self):
        if not self.items:
            print("El carrito está vacío.")
            return
        print("Productos en el carrito:")
        for producto, cantidad in self.items.items():
            print(f"- {producto.nombre} | Cantidad: {cantidad} | P. Unitario: ${producto.precio}")
    
    def documentar_compra(self):
        if not self.items:
            print("No hay productos para documentar.")
            return
        print("Documentando compra...")
        for producto, cantidad in self.items.items():
            print(f"Producto: {producto.nombre}, Cantidad: {cantidad}, Precio Unitario: ${producto.precio}")

    def mostrar_total(self):
        total_precio = self.calcular_total()
        total_items = sum(cantidad for cantidad in self.items.values())
        print(f"Total de artículos: {total_items}, Precio total: ${total_precio}")

    def calcular_total(self):
        return sum(producto.precio * cantidad for producto, cantidad in self.items.items())

    def esta_vacio(self):
        return len(self.items) == 0

# ==========================================
# 2. USUARIOS Y ROLES (HERENCIA CORRECTA)
# ==========================================

class Usuario:
    def __init__(self, nombre, direccion, celular, email, username=None, tipo='cliente', puntos=0):
        self.nombre = nombre
        self.direccion = direccion
        self.celular = celular
        self.email = email
        self.username = username or email
        self.tipo = tipo
        self.puntos = puntos

    def mostrar_informacion(self):
        print(f"Usuario: {self.nombre}, Dirección: {self.direccion}, Celular: {self.celular}, Email: {self.email}, Tipo: {self.tipo}")


class Administrador(Usuario):
    def __init__(self, nombre, direccion, celular, email, username=None, puntos=0):
        super().__init__(nombre, direccion, celular, email, username=username, tipo='administrador', puntos=puntos)
    
    def agregar_usuario(self, mercado, usuario):
        mercado.usuarios.append(usuario)
    
    def eliminar_usuario(self, mercado, usuario):
        if usuario in mercado.usuarios:
            mercado.usuarios.remove(usuario)

    def suspender_usuario(self, mercado, usuario):
        if usuario in mercado.usuarios:
            mercado.usuarios.remove(usuario)
            print(f"Usuario {usuario.nombre} ha sido suspendido.")
        else:
            print(f"Usuario {usuario.nombre} no encontrado en el mercado.")
    
    def agregar_tienda(self, mercado, tienda):
        mercado.agregar_tienda(tienda)
    
    def eliminar_tienda(self, mercado, tienda):
        if tienda in mercado.tiendas:
            mercado.tiendas.remove(tienda)

    def agregar_producto(self, tienda, producto):
        tienda.agregar_producto(producto)
    
    def eliminar_producto(self, tienda, producto):
        if producto in tienda.productos:
            tienda.productos.remove(producto)

    def modificar_precio_producto(self, producto, nuevo_precio):
        producto.precio = nuevo_precio

    def generar_reportes(self, mercado):
        print(f"\n===== REPORTE DE: {mercado.nombre} =====")
        print(f"Total de tiendas: {len(mercado.tiendas)}")
        
        if not mercado.tiendas:
            print("El mercado no tiene tiendas registradas.")
            return

        todos_los_productos = [p for t in mercado.tiendas for p in t.productos]
        
        # Validar si hay productos para evitar errores de secuencia vacía
        if todos_los_productos:
            total_inventario_valor = sum(p.precio * p.unidades for p in todos_los_productos)
            print(f"Valor total del inventario en tiendas: ${total_inventario_valor}")
            
            # En base a tu lógica original (unidades = stock), esto busca el que tiene más stock disponible
            mas_abastecido = max(todos_los_productos, key=lambda p: p.unidades)
            print(f"Producto con mayor stock disponible: {mas_abastecido.nombre} ({mas_abastecido.unidades} uds)")
        else:
            print("No hay productos registrados en ninguna tienda.")


class Cliente(Usuario):
    def __init__(self, nombre, direccion, celular, email, username=None, puntos=0):
        super().__init__(nombre, direccion, celular, email, username=username, tipo='cliente', puntos=puntos)
        self.carrito = Carrito()
    
    def agregar_al_carrito(self, producto, cantidad=1):
        self.carrito.agregar_producto(producto, cantidad)
    
    def eliminar_del_carrito(self, producto):
        self.carrito.borrar_productos(producto)


class Vendedor(Usuario):
    def __init__(self, nombre, direccion, celular, email, username=None, puntos=0):
        super().__init__(nombre, direccion, celular, email, username=username, tipo='vendedor', puntos=puntos)
    
    def agregar_tienda(self, mercado, tienda):
        mercado.agregar_tienda(tienda)       

    def agregar_producto(self, tienda, producto):
        tienda.agregar_producto(producto)

# ==========================================
# 3. CAPA DE PERSISTENCIA (SQLITE)
# ==========================================

def _db_path():
    return os.environ.get(
        'MARKETPLACE_DB',
        os.path.join(os.path.dirname(__file__), 'marketplace.db')
    )


def _connect(db_path=None):
    db = db_path or _db_path()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db(db_path=None):
    with _connect(db_path) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY, nombre TEXT, direccion TEXT, celular TEXT,
            email TEXT, username TEXT, tipo TEXT, puntos INTEGER
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS mercados (
            id INTEGER PRIMARY KEY, nombre TEXT, direccion TEXT, celular TEXT, email TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS tiendas (
            id INTEGER PRIMARY KEY, mercado_id INTEGER, nombre TEXT, direccion TEXT,
            celular TEXT, giro TEXT, FOREIGN KEY(mercado_id) REFERENCES mercados(id)
        )''')
        
        columnas_tiendas = [row[1] for row in c.execute("PRAGMA table_info(tiendas)")]
        if "codigo_postal" not in columnas_tiendas:
            c.execute("ALTER TABLE tiendas ADD COLUMN codigo_postal TEXT")
            
        if "vendedor_username" not in columnas_tiendas:
            c.execute("ALTER TABLE tiendas ADD COLUMN vendedor_username TEXT")
        
        c.execute('''CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY, tienda_id INTEGER, nombre TEXT, unidades INTEGER,
            precio REAL, presentacion TEXT, imagen TEXT, logistics_size TEXT,
            FOREIGN KEY(tienda_id) REFERENCES tiendas(id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY,
            username TEXT,
            total REAL,
            created_at TEXT,
            destination_context TEXT,
            delivery_cp TEXT,
            shipping_initial REAL,
            logistics_status TEXT,
            logistics_estimated_space TEXT,
            logistics_actual_space TEXT,
            logistics_assessment TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS pedido_items (
            id INTEGER PRIMARY KEY, pedido_id INTEGER, producto_id INTEGER,
            unidades INTEGER, precio REAL, FOREIGN KEY(pedido_id) REFERENCES pedidos(id),
            FOREIGN KEY(producto_id) REFERENCES productos(id)
        )''')
        existing_product_columns = [row[1] for row in c.execute('PRAGMA table_info(productos)')]
        if 'vendedor_username' not in existing_product_columns:
            c.execute('ALTER TABLE productos ADD COLUMN vendedor_username TEXT')

        if 'logistics_size' not in existing_product_columns:
            c.execute('ALTER TABLE productos ADD COLUMN logistics_size TEXT')

        if 'categoria' not in existing_product_columns:
            c.execute('ALTER TABLE productos ADD COLUMN categoria TEXT')
        
        # Validación de la columna username
        existing_pedidos = [row[1] for row in conn.execute('PRAGMA table_info(pedidos)')]
        if 'username' not in existing_pedidos:
            conn.execute('ALTER TABLE pedidos ADD COLUMN username TEXT')

        if 'destination_context' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN destination_context TEXT'
            )

        if 'delivery_cp' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN delivery_cp TEXT'
            )

        if 'shipping_initial' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN shipping_initial REAL'
            )

        if 'logistics_status' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN logistics_status TEXT'
            )

        if 'logistics_estimated_space' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN logistics_estimated_space TEXT'
            )

        if 'logistics_actual_space' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN logistics_actual_space TEXT'
            )

        if 'logistics_assessment' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN logistics_assessment TEXT'
            )

        if 'calkini_locality' not in existing_pedidos:
            conn.execute(
                'ALTER TABLE pedidos ADD COLUMN calkini_locality TEXT'
            )


def existe_mercado(db_path=None) -> bool:
    with _connect(db_path) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(1) FROM mercados')
        return c.fetchone()[0] > 0


def save_mercado(mercado, db_path=None):
    with _connect(db_path) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO mercados (nombre, direccion, celular, email) VALUES (?, ?, ?, ?)',
                  (mercado.nombre, mercado.direccion, mercado.celular, mercado.email))
        return c.lastrowid


def save_tienda(tienda, mercado_id, vendedor_username=None, db_path=None):
    with _connect(db_path) as conn:
        c = conn.cursor()

        c.execute('''
            INSERT INTO tiendas
            (mercado_id, nombre, direccion, celular, giro, codigo_postal, vendedor_username)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            mercado_id,
            tienda.nombre,
            tienda.direccion,
            tienda.celular,
            tienda.giro,
            tienda.codigo_postal,
            vendedor_username
        ))

        return c.lastrowid

def save_producto(
    producto,
    tienda_id,
    vendedor_username=None,
    precio_proveedor=None,
    logistics_size=None,
    categoria=None,
    db_path=None
):
    with _connect(db_path) as conn:
        c = conn.cursor()

        c.execute('''
            INSERT INTO productos
            (
                tienda_id,
                nombre,
                unidades,
                precio,
                presentacion,
                imagen,
                vendedor_username,
                precio_proveedor,
                logistics_size,
                categoria
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tienda_id,
            producto.nombre,
            producto.unidades,
            producto.precio,
            producto.presentacion,
            getattr(producto, 'imagen', None),
            vendedor_username,
            precio_proveedor,
            logistics_size,
            categoria
        ))

        return c.lastrowid
        
def persistir_demo_si_no_existe(mercado1, db_path=None):
    if existe_mercado(db_path):
        return
    mercado_id = save_mercado(mercado1, db_path=db_path)
    for tienda in mercado1.tiendas:
        tienda_id_db = save_tienda(tienda, mercado_id, db_path=db_path)
        for producto in tienda.productos:
            save_producto(producto, tienda_id_db, db_path=db_path)


def crear_tiendas_demo():
    # Inicializar Base de datos
    init_db()

    # Creación de Objetos en Memoria (POO)
    mercado1 = Mercado("Mercado Central", "Mérida, Yucatán", "9999152637", "central@market.com")
    
    tienda1 = Tienda("Coscorron", "Mérida, Yucatán", "5588182650", "abarrotes")
    tienda2 = Tienda("Walmart", "Mérida, Yucatán", "9999152637", "cerveceria")
    tienda3 = Tienda("Chedraui", "Mérida, Yucatán", "9999152637", "abarrotes")

    mercado1.agregar_tienda(tienda1)
    mercado1.agregar_tienda(tienda2)
    mercado1.agregar_tienda(tienda3)

    producto1 = Producto(
    "Coca-Cola",
    50,
    20,
    "Botella de 500ml",
    "carrito.jpg"
)
    producto2 = Producto("Pepsi", 40, 18, "Lata de 330ml")                 
    producto3 = Producto("Arizona", 24, 20, "Lata de 500ml")
    producto4 = Producto("Dos XX lager", 12, 20, "Lata de 355ml")
    producto5 = Producto("Malboro", 10, 80, "Rojos de 20")

    tienda1.agregar_producto(producto1)
    tienda1.agregar_producto(producto2)
    tienda1.agregar_producto(producto3)
    tienda2.agregar_producto(producto4)
    tienda2.agregar_producto(producto5)
    tienda3.agregar_producto(producto1)  # Copias de productos
    tienda3.agregar_producto(producto2)

    return mercado1


def menu_principal() -> bool:
    init_user_db()
    print("Bienvenido al sistema de marketplace.")
    while True:
        print("\nOpciones:")
        print("1) Crear cuenta")
        print("2) Iniciar sesión")
        print("3) Salir")
        opcion = input("Elige una opción (1/2/3): ").strip()
        if opcion == '1':
            if create_account_interactive():
                print("Cuenta creada correctamente. Ya puedes iniciar sesión.")
            continue
        if opcion == '2':
            if login_interactive():
                print("Acceso concedido.")
                return True
            print("No se pudo iniciar sesión. Intenta de nuevo.")
            continue
        if opcion == '3':
            print("Saliendo.")
            return False
        print("Opción no válida. Intenta de nuevo.")


def seleccionar_tienda(mercado):
    if not mercado.tiendas:
        print("No hay tiendas disponibles.")
        return None
    for idx, tienda in enumerate(mercado.tiendas, start=1):
        print(f"{idx}) {tienda.nombre} - {tienda.giro}")
    seleccion = input("Elige el número de tienda (o 0 para volver): ").strip()
    if not seleccion.isdigit() or int(seleccion) < 0 or int(seleccion) > len(mercado.tiendas):
        print("Selección inválida.")
        return None
    indice = int(seleccion)
    if indice == 0:
        return None
    return mercado.tiendas[indice - 1]


def seleccionar_producto(tienda):
    if not tienda.productos:
        print("No hay productos en esta tienda.")
        return None
    for idx, producto in enumerate(tienda.productos, start=1):
        print(f"{idx}) {producto.nombre} - ${producto.precio} - Stock: {producto.unidades}")
    seleccion = input("Elige el número de producto (o 0 para volver): ").strip()
    if not seleccion.isdigit() or int(seleccion) < 0 or int(seleccion) > len(tienda.productos):
        print("Selección inválida.")
        return None
    indice = int(seleccion)
    if indice == 0:
        return None
    return tienda.productos[indice - 1]


def menu_cliente(cliente, mercado):
    print(f"\nHola {cliente.nombre}, bienvenido al marketplace.")
    while True:
        print("\nMenú de cliente:")
        print("1) Ver tiendas")
        print("2) Ver productos de una tienda")
        print("3) Agregar producto al carrito")
        print("4) Ver carrito")
        print("5) Mostrar total del carrito")
        print("6) Pagar carrito")
        print("7) Salir")
        opcion = input("Elige una opción (1-7): ").strip()

        if opcion == '1':
            mercado.mostrar_tiendas()
            continue

        if opcion == '2':
            tienda = seleccionar_tienda(mercado)
            if tienda:
                tienda.mostrar_productos()
            continue

        if opcion == '3':
            tienda = seleccionar_tienda(mercado)
            if tienda:
                producto = seleccionar_producto(tienda)
                if producto:
                    cantidad = input("Cantidad a agregar: ").strip()
                    if cantidad.isdigit() and int(cantidad) > 0:
                        cantidad = int(cantidad)
                        if cantidad <= producto.unidades:
                            cliente.agregar_al_carrito(producto, cantidad)
                            print(f"{cantidad} unidades de {producto.nombre} agregadas al carrito.")
                        else:
                            print("No hay suficiente stock disponible.")
                    else:
                        print("Cantidad inválida.")
            continue

        if opcion == '4':
            cliente.carrito.mostrar_carrito()
            continue

        if opcion == '5':
            cliente.carrito.mostrar_total()
            continue

        if opcion == '6':
            if cliente.carrito.esta_vacio():
                print("El carrito está vacío. Agrega productos antes de pagar.")
                continue
            total = cliente.carrito.calcular_total()
            print(f"Total a pagar: ${total}")
            print("Pago procesado. Gracias por tu compra.")
            cliente.carrito.items.clear()
            continue

        if opcion == '7':
            print("Cerrando sesión de cliente.")
            break

        print("Opción no válida. Intenta de nuevo.")


if __name__ == '__main__':
    if menu_principal():
        # Crea los objetos demo en memoria
        mi_mercado = crear_tiendas_demo()

        # Persiste los datos de demostración solo una vez
        init_db()
        persistir_demo_si_no_existe(mi_mercado)

        # Crea un cliente para la sesión interactiva
        cliente_sesion = Cliente("Cliente Demo", "Dirección Demo", "0000000000", "cliente@demo.com")
        menu_cliente(cliente_sesion, mi_mercado)
    else:
        print("Aplicación cerrada.")
