import io
import csv
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, Response, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.config['SECRET_KEY'] = 'clave-secreta-stockflow-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stockflow.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, inicia sesión para acceder al sistema.'
login_manager.login_message_category = 'error'

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    stock_minimo = db.Column(db.Integer, nullable=False, default=5)
    precio = db.Column(db.Float, nullable=False)

class Movimiento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    fecha = db.Column(db.String(50), nullable=False)
    
    producto = db.relationship('Producto', backref=db.backref('movimientos', lazy=True))

with app.app_context():
    db.create_all()
    if not Usuario.query.first():
        hashed_password = generate_password_hash('Admin123*', method='pbkdf2:sha256')
        admin = Usuario(email='admin@stockflow.com', password=hashed_password)
        db.session.add(admin)
        db.session.commit()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and check_password_hash(usuario.password, password):
            login_user(usuario)
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas.', 'error')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    per_page = 5  # Productos por página
    
    pagination = Producto.query.paginate(page=page, per_page=per_page, error_out=False)
    productos = pagination.items
    
    todos_productos = Producto.query.all()
    movimientos = Movimiento.query.order_by(Movimiento.id.desc()).limit(10).all()
    alertas = [p for p in todos_productos if p.stock <= p.stock_minimo]
    
    total_valor = sum(p.stock * p.precio for p in todos_productos)
    total_items = sum(p.stock for p in todos_productos)
    
    # Agrupar datos para el gráfico de categorías
    categorias_dict = {}
    for p in todos_productos:
        categorias_dict[p.categoria] = categorias_dict.get(p.categoria, 0) + (p.stock * p.precio)
    
    cat_labels = list(categorias_dict.keys())
    cat_data = list(categorias_dict.values())
    
    return render_template('dashboard.html', 
                           productos=productos, 
                           pagination=pagination,
                           movimientos=movimientos, 
                           alertas=alertas,
                           total_valor=total_valor,
                           total_items=total_items,
                           cat_labels=cat_labels,
                           cat_data=cat_data)

@app.route('/producto/nuevo', methods=['POST'])
@login_required
def agregar_producto():
    sku = request.form['sku']
    nombre = request.form['nombre']
    categoria = request.form['categoria']
    stock = int(request.form['stock'])
    stock_minimo = int(request.form['stock_minimo'])
    precio = float(request.form['precio'])

    nuevo = Producto(sku=sku, nombre=nombre, categoria=categoria, stock=stock, stock_minimo=stock_minimo, precio=precio)
    db.session.add(nuevo)
    db.session.commit()
    
    if stock > 0:
        mov = Movimiento(producto_id=nuevo.id, tipo='Entrada Inicial', cantidad=stock, fecha=datetime.now().strftime("%Y-%m-%d %H:%M"))
        db.session.add(mov)
        db.session.commit()
        
    return redirect(url_for('dashboard'))

@app.route('/producto/movimiento/<int:id>', methods=['POST'])
@login_required
def registrar_movimiento(id):
    producto = Producto.query.get_or_404(id)
    tipo = request.form['tipo']
    cantidad = int(request.form['cantidad'])
    
    if tipo == 'Salida':
        if producto.stock < cantidad:
            flash(f'Stock insuficiente para {producto.nombre}.', 'error')
            return redirect(url_for('dashboard'))
        producto.stock -= cantidad
    else:
        producto.stock += cantidad
        
    mov = Movimiento(producto_id=producto.id, tipo=tipo, cantidad=cantidad, fecha=datetime.now().strftime("%Y-%m-%d %H:%M"))
    db.session.add(mov)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/producto/eliminar/<int:id>')
@login_required
def eliminar_producto(id):
    producto = Producto.query.get_or_404(id)
    Movimiento.query.filter_by(producto_id=producto.id).delete()
    db.session.delete(producto)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/exportar/csv')
@login_required
def exportar_csv():
    productos = Producto.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['SKU', 'Nombre', 'Categoría', 'Stock', 'Stock Mínimo', 'Precio Unitario (€)'])
    for p in productos:
        writer.writerow([p.sku, p.nombre, p.categoria, p.stock, p.stock_minimo, p.precio])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment; filename=inventario_stockflow.csv"}
    )

@app.route('/factura/<int:id>')
@login_required
def generar_factura(id):
    producto = Producto.query.get_or_404(id)
    
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    
    p.setFont("Helvetica-Bold", 20)
    p.drawString(50, 750, "STOCKFLOW - FACTURA COMERCIAL")
    
    p.setFont("Helvetica", 12)
    p.drawString(50, 710, f"Fecha de Emisión: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    p.drawString(50, 680, f"SKU de Referencia: {producto.sku}")
    p.drawString(50, 660, f"Artículo: {producto.nombre}")
    p.drawString(50, 640, f"Categoría: {producto.categoria}")
    p.drawString(50, 620, f"Stock Actual Registrado: {producto.stock} unidades")
    p.drawString(50, 600, f"Precio Unitario: {producto.precio:.2f} €")
    
    p.line(50, 580, 550, 580)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, 550, f"Valor Total en Stock: {(producto.stock * producto.precio):.2f} €")
    
    p.showPage()
    p.save()
    
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={"Content-Disposition": f"attachment; filename=factura_{producto.sku}.pdf"}
    )

if __name__ == '__main__':
    app.run(debug=True)