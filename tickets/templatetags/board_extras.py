from django import template

register = template.Library()


@register.filter(name='as_list')
def as_list(obj):
    """Envuelve un objeto en una lista de un solo elemento. Útil para pasar un único
    Assignment como `assignments` al avatar-stack del footer, mostrando solo el avatar
    del ejecutor que está en esa card (no todos los asignados del ticket)."""
    return [obj]


@register.filter(name='divide_family_ids')
def divide_family_ids(t):
    """pk del padre de `t` + pks de sus otras partes (hermanas), excluyendo a `t` mismo,
    unidos por coma — para `data-highlight-siblings` en el ícono de tijera. Incluye al
    padre a propósito: con una sola parte dividida no hay hermanas, pero sí hay que
    resaltar el padre — si no, clickear la tijera no resaltaba nada (ver
    static/js/subdivide-highlight.js)."""
    if not t.parent_id:
        return ''
    ids = [str(t.parent_id)]
    ids += [str(c.pk) for c in t.parent.children.all() if c.pk != t.pk]
    return ','.join(ids)


@register.filter(name='selected_in')
def selected_in(pk, values):
    """True si `pk` está entre los valores seleccionados de un campo M2M del form —
    compara como strings porque `BoundField.value()` devuelve strings tras un POST
    pero pks (ints) cuando viene del initial de una instancia."""
    if not values:
        return False
    return str(pk) in {str(v) for v in values}


@register.filter(name='has_divided_child')
def has_divided_child(children):
    """True si alguno de `children` es una parte dividida (`is_divided_part`) — para que
    el ícono de "tiene hijos" del padre (tablero y detalle) muestre tijera/"Dividido" en
    vez de flecha/"Derivado" cuando corresponde. Sin esto, un padre con hijos de Dividir
    (no de Derivar) mostraba igual el ícono y el texto de "Derivado", porque ese ícono
    nunca distinguía el origen."""
    return any(c.is_divided_part for c in children)