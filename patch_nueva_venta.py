from pathlib import Path

path = Path(r'c:\Users\Eva Celeste\Downloads\SEDUCA\NuevaModa\app.py')
text = path.read_text(encoding='utf-8')
marker = 'def nueva_venta():'
idx = text.find(marker)
if idx == -1:
    raise SystemExit('def nueva_venta() not found')
next_deco = text.find('@app.route("/ventas/<int:id>")', idx + len(marker))
if next_deco == -1:
    raise SystemExit('next decorator not found')
insert = "\n    productos = filtro_unidad(Producto.query, Producto).filter(Producto.stock > 0).all()\n    clientes = filtro_unidad(Cliente.query, Cliente).all()\n    config = Configuracion.query.first()\n\n    if not config:\n        flash(\"No hay configuración creada\", \"danger\")\n        return redirect(url_for(\"configuracion\"))\n\n    if request.method == \"POST\":\n        flash(\"Funcionalidad de creación de ventas pendiente\", \"warning\")\n        return redirect(url_for(\"ventas\"))\n\n    return render_template(\"nueva_venta.html\", productos=productos, clientes=clientes, config=config)\n"
text = text[:idx + len(marker)] + insert + text[next_deco:]
path.write_text(text, encoding='utf-8')
print('patched')
