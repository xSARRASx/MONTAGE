"""Éléments 3D du style « sobre » (beige / blanc papier / vert sauge), avec ombres réelles.

Usage : python3 render3d_sobre.py <element> <dossier_sortie> [samples] [image_seule] [threads]
Rendu sur fond transparent ; l'ombre portée douce est ajoutée au compositing (composite_sobre.py).
"""
import bpy, bmesh, math, os, sys
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render3d as R
from render3d import mat, empty, prim, box, bevel, smooth, extrude_poly, lin, ease_out, ease_out_back, ease_in, Anim

PAPER, SAGE, INK, MUTED, BRASS = '#FBFAF6', '#5B8A6E', '#262B28', '#B9BDB6', '#B59C6B'
_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'fonts')
FONT_B = os.path.join(_FONTS, 'Manrope-800.ttf')
FONT_R = os.path.join(_FONTS, 'Manrope-600.ttf')
FONT_B = os.environ.get('FONT_B', FONT_B); FONT_R = os.environ.get('FONT_R', FONT_R)

def paper(): return mat(PAPER, rough=0.65, coat=0.0)
def sage(): return mat(SAGE, rough=0.45, coat=0.2)
def ink(): return mat(INK, rough=0.5, coat=0.0)
def muted(): return mat(MUTED, rough=0.7, coat=0.0)

def scene(resx, resy, samples, cam_loc, target=(0, 0, 0), lens=50):
    sc = R.reset(resx, resy, samples)
    sc.view_settings.exposure = 0.0
    cam = sc.camera; cam.location = cam_loc; cam.data.lens = lens
    d = Vector(target) - Vector(cam_loc); cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    # éclairage doux type studio : grande source clé au-dessus, pour des ombres diffuses
    for o in list(bpy.data.objects):
        if o.type == 'LIGHT': bpy.data.objects.remove(o)
    R.light('Key', (-3, -3, 9), 1400, 9, '#FFF8EE')
    R.light('Fill', (6, -6, 3), 300, 8, '#FFFFFF')
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.6
    # pas de plan « shadow catcher » (trop coûteux en CPU) : l'ombre douce est ajoutée au compositing
    return sc

def text(body, parent, m, size, loc, font=FONT_B, flat=True, align='LEFT'):
    cu = bpy.data.curves.new('T', 'FONT'); cu.body = body
    cu.font = bpy.data.fonts.load(font, check_existing=True)
    cu.size = size; cu.extrude = 0.004; cu.align_x = align; cu.align_y = 'CENTER'
    o = bpy.data.objects.new('T', cu); R.link(o, parent); o.data.materials.append(m)
    o.location = loc
    return o

def rounded_rect(w, h, r, n=8):
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n); pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts

def flat_slab(pts, thick, parent, m, bev=0.02, name='slab'):
    """Polygone (x, y) extrudé vers le haut (Z), posé sur la table."""
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    f = bm.faces.new([bm.verts.new((x, y, 0)) for x, y in pts])
    bmesh.ops.recalc_face_normals(bm, faces=[f])
    if f.normal.z > 0: f.normal_flip()
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    bmesh.ops.translate(bm, verts=[g for g in r['geom'] if isinstance(g, bmesh.types.BMVert)], vec=(0, 0, thick))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); R.link(o, parent, m)
    if bev: bevel(o, bev, 3)
    return o

# ------------------------------------------------------------------ 3 contrats signés
def contract(parent, loc, rot):
    c = empty('contract', parent, loc); c.rotation_euler = (0, 0, math.radians(rot))
    flat_slab(rounded_rect(2.1, 2.8, 0.04), 0.03, c, paper(), 0.01)
    text('CONTRAT', c, ink(), 0.17, (-0.85, 1.12, 0.035))
    text('de gestion locative', c, muted(), 0.1, (-0.85, 0.92, 0.035), FONT_R)
    for i in range(9):
        w = 1.7 if i % 4 != 3 else 1.1
        box(c, muted(), (-0.85 + w / 2, 0.62 - i * 0.16, 0.034), (w, 0.045, 0.004), 0)
    box(c, ink(), (-0.25, -0.98, 0.034), (1.2, 0.012, 0.004), 0)          # ligne de signature
    # signature manuscrite (courbe)
    cu = bpy.data.curves.new('sig', 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = 0.012
    sp = cu.splines.new('POLY'); pts = []
    for k in range(40):
        t = k / 39; pts.append((-0.8 + 1.1 * t, -0.86 + 0.13 * math.sin(t * 17) * (1 - 0.5 * t) + 0.05 * math.sin(t * 5), 0.045))
    sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts): p.co = (*q, 1)
    sig = bpy.data.objects.new('sig', cu); R.link(sig, c); sig.data.materials.append(ink())
    return c, sig

def seal(parent, loc):
    st = empty('seal', parent, loc)
    d = prim('cylinder', st, sage(), (0, 0, 0.05), vertices=64, radius=0.42, depth=0.1); smooth(d); bevel(d, 0.02, 3)
    r = prim('torus', st, mat('#4A765C', rough=0.5), (0, 0, 0.1), major_radius=0.34, minor_radius=0.02); smooth(r)
    ck = R.check_mark(st, mat(PAPER, rough=0.4), 0.45, (0, 0, 0), 0.03)
    ck.rotation_euler = (math.radians(-90), 0, 0); ck.location = (0, 0.0, 0.11)
    return st

def el_contracts(samples):
    """3 contrats qui se posent en éventail, signature qui s'écrit, puis tampon vert « signé » sur chacun."""
    N = 105
    sc = scene(1000, 820, samples, (0, -6.8, 9.0), (0, -0.1, 0), lens=48)
    items = []
    for i, (x, y, rot) in enumerate(((-2.05, 0.05, 6), (0, 0.25, -2), (2.05, 0.0, -7))):
        c, sig = contract(None, (x, y, 0.04 * i), rot)
        st = seal(c, (0.62, -0.95, 0.04))
        items.append((c, sig, st, (x, y, rot)))
    a = Anim(N)
    starts = [2, 9, 16]
    @a.on
    def _(f):
        for i, (c, sig, st, (x, y, rot)) in enumerate(items):
            k = lin(f, starts[i], starts[i] + 16); e = ease_out(k)
            c.location = (x + 0.8 * (1 - e) * (i - 1), y - 1.2 * (1 - e), 0.04 * i + 3.5 * (1 - e) ** 2)
            c.rotation_euler = (math.radians(-35 * (1 - e)), 0, math.radians(rot - 25 * (1 - e)))
            c.scale = (max(1e-4, min(1, k * 3)),) * 3
            sg = lin(f, 30 + 6 * i, 46 + 6 * i)
            sig.data.bevel_factor_end = max(0.001, ease_out(sg))
            st.scale = (max(1e-4, ease_out_back(lin(f, 56 + 7 * i, 66 + 7 * i), 2.4)),) * 3
            st.location.z = 0.04 + 0.8 * (1 - ease_out(lin(f, 56 + 7 * i, 64 + 7 * i)))
    a.bake([it[0] for it in items] + [it[2] for it in items])
    return N, [(it[1], i) for i, it in enumerate(items)]

# ------------------------------------------------------------------ maison minimaliste
def el_house(samples):
    """Maison épurée papier blanc + toit sauge, sur un socle rond, qui pivote lentement."""
    N = 120
    sc = scene(760, 760, samples, (0, -8.0, 5.2), (0, 0, 1.0), lens=50)
    root = empty('root')
    base = prim('cylinder', root, paper(), (0, 0, 0.08), vertices=96, radius=2.2, depth=0.16); smooth(base); bevel(base, 0.03, 3)
    h = empty('house', root, (0, 0, 0.16))
    box(h, paper(), (0, 0, 0.8), (2.0, 1.6, 1.6), 0.03)
    roof = extrude_poly([(-1.3, 1.55), (1.3, 1.55), (0, 2.65)], 1.9, h, sage(), 0.03, 'roof')
    box(h, sage(), (0.55, 0.3, 2.35), (0.28, 0.28, 0.6), 0.02)
    box(h, ink(), (-0.35, -0.82, 0.55), (0.5, 0.06, 1.0), 0.02)
    for x in (0.5,):
        box(h, mat('#DCE3DD', rough=0.1, coat=1), (x, -0.82, 0.95), (0.5, 0.05, 0.5), 0.02)
    for x, y in ((-1.5, 0.9), (1.55, -0.6)):
        t = empty('tree', root, (x, y, 0.16))
        s = prim('uv_sphere', t, mat('#8FB39C', rough=0.6), (0, 0, 0.75), radius=0.38); smooth(s); s.scale = (1, 1, 1.3)
        box(t, mat('#9C8B72', rough=0.7), (0, 0, 0.2), (0.08, 0.08, 0.4), 0.01)
    a = Anim(N)
    @a.on
    def _(f):
        root.scale = (max(1e-4, ease_out_back(lin(f, 1, 18), 1.3)),) * 3
        root.rotation_euler = (0, 0, math.radians(-38 + 40 * ease_out(lin(f, 1, N)) ))
        h.location.z = 0.16 + 1.8 * (1 - ease_out(lin(f, 4, 22)))
    a.bake([root, h])
    return N

# ------------------------------------------------------------------ bloc « revenu » dont 25 % se détache
def el_split(samples):
    """Bloc blanc = revenu locatif ; le quart supérieur (vert) se soulève et glisse : ta commission."""
    N = 125
    sc = scene(760, 860, samples, (0.8, -8.2, 4.6), (0.4, 0, 1.9), lens=50)
    root = empty('root')
    low = empty('low', root); top = empty('top', root, (0, 0, 2.7))
    box(low, paper(), (0, 0, 1.35), (1.6, 1.6, 2.7), 0.06)
    box(top, sage(), (0, 0, 0.45), (1.6, 1.6, 0.9), 0.06)
    a = Anim(N)
    @a.on
    def _(f):
        g = ease_out(lin(f, 2, 24))
        low.scale = (1, 1, max(1e-3, g)); top.scale = (max(1e-4, min(1, g * 2)),) * 3
        up = ease_out_back(lin(f, 40, 60), 1.4)
        slide = ease_out(lin(f, 52, 72))
        top.location = (1.9 * slide, 0, 2.7 * g + 0.9 * up - 0.5 * slide)
        top.rotation_euler = (0, math.radians(-8 * up * (1 - slide)), math.radians(8 * slide))
        root.rotation_euler = (0, 0, math.radians(-28 + 10 * math.sin(f / 40)))
    a.bake([root, low, top])
    return N

ELEMENTS = dict(contracts=el_contracts, house=el_house, split=el_split)

def main():
    args = sys.argv[1:]
    name, out = args[0], args[1]
    samples = int(args[2]) if len(args) > 2 else 16
    only = int(args[3]) if len(args) > 3 else 0
    threads = int(args[4]) if len(args) > 4 else 0
    res = ELEMENTS[name](samples)
    N, sigs = res if isinstance(res, tuple) else (res, [])
    sc = bpy.context.scene
    if threads: sc.render.threads_mode = 'FIXED'; sc.render.threads = threads
    os.makedirs(out, exist_ok=True)
    for f in ([only] if only else range(1, N + 1)):
        p = os.path.join(out, '%s_%04d.png' % (name, f))
        if os.path.exists(p) and not only: continue
        sc.frame_set(f); sc.render.filepath = p
        for sig, i in sigs:   # la signature « s'écrit » (propriété non animable par keyframe ici)
            sig.data.bevel_factor_end = max(0.001, ease_out(lin(f, 30 + 6 * i, 46 + 6 * i)))
        bpy.ops.render.render(write_still=True)
    print('DONE', name, N)

if __name__ == '__main__':
    main()
