"""Éléments 3D animés (Blender / bpy, rendu Cycles avec fond transparent).

Usage : python3 render3d.py <element> <dossier_sortie> [samples]
Chaque élément est rendu en séquence PNG RGBA à 30 i/s, puis composité sur la vidéo par composite.py.
La caméra regarde vers +Y : les formes 2D sont dessinées dans le plan XZ puis extrudées en Y.
"""
import bpy, bmesh, math, os, sys, glob
from mathutils import Vector

FONT = '/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Black.ttf'
FPS = 30

# ---------------------------------------------------------------- utilitaires

def srgb(h):
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1,)

# Palette sobre « noir laqué + or » : ne concurrence pas l'orange/bleu des bandeaux déjà incrustés.
WHITE, GOLD, CREAM, BLACK = '#F4F2EC', '#E9B949', '#FFF4E6', '#131417'

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def lin(f, a, b): return clamp((f - a) / max(1e-6, b - a))
def ease_out_back(x, s=1.9):
    x = clamp(x); return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2
def ease_out_elastic(x):
    x = clamp(x)
    if x in (0, 1): return x
    return 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi / 3)) + 1
def ease_in_out(x):
    x = clamp(x); return 3 * x * x - 2 * x * x * x
def ease_out(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_in(x): x = clamp(x); return x ** 3
def bounce(x):
    x = clamp(x); n, d = 7.5625, 2.75
    if x < 1 / d: return n * x * x
    if x < 2 / d: x -= 1.5 / d; return n * x * x + .75
    if x < 2.5 / d: x -= 2.25 / d; return n * x * x + .9375
    x -= 2.625 / d; return n * x * x + .984375

def reset(resx, resy, samples, cam_dist=10, lens=50, cam_z=0):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'
    sc.cycles.samples = samples; sc.cycles.use_denoising = True
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.max_bounces = 4; sc.cycles.diffuse_bounces = 2; sc.cycles.glossy_bounces = 2
    sc.cycles.transmission_bounces = 2; sc.cycles.transparent_max_bounces = 4
    sc.cycles.caustics_reflective = sc.cycles.caustics_refractive = False
    sc.cycles.adaptive_threshold = 0.03
    sc.render.film_transparent = True
    sc.render.resolution_x, sc.render.resolution_y = resx, resy
    sc.render.fps = FPS
    sc.render.use_motion_blur = True; sc.render.motion_blur_shutter = 0.5
    sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.exposure = -0.35
    # monde : HDRI studio pour de beaux reflets (invisible car fond transparent)
    w = bpy.data.worlds.new('W'); sc.world = w; w.use_nodes = True
    nt = w.node_tree; env = nt.nodes.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(glob.glob(bpy.utils.system_resource('DATAFILES') + '/studiolights/world/studio.exr')[0])
    bg = nt.nodes['Background']; bg.inputs['Strength'].default_value = 0.9
    nt.links.new(env.outputs['Color'], bg.inputs['Color'])
    cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam'))
    sc.collection.objects.link(cam); sc.camera = cam
    cam.location = (0, -cam_dist, cam_z); cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.lens = lens
    light('Key', (4, -6, 5), 900, 5, CREAM)
    light('Rim', (-5, 4, 3), 800, 4, '#FFF6EA')
    light('Fill', (-5, -5, -1), 250, 6, '#FFFFFF')
    return sc

def light(name, loc, energy, size, col):
    L = bpy.data.lights.new(name, 'AREA'); L.energy = energy; L.size = size; L.color = srgb(col)[:3]
    o = bpy.data.objects.new(name, L); bpy.context.scene.collection.objects.link(o)
    o.location = loc
    d = Vector((0, 0, 0)) - Vector(loc); o.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return o

_mats = {}
def mat(col, metal=0.0, rough=0.35, coat=0.6, emit=0.0):
    key = (col, metal, rough, coat, emit)
    if key in _mats: return _mats[key]
    m = bpy.data.materials.new(str(key)); m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = srgb(col)
    p.inputs['Metallic'].default_value = metal; p.inputs['Roughness'].default_value = rough
    p.inputs['Coat Weight'].default_value = coat; p.inputs['Coat Roughness'].default_value = 0.08
    if emit:
        p.inputs['Emission Color'].default_value = srgb(col); p.inputs['Emission Strength'].default_value = emit
    _mats[key] = m
    return m

def blk(): return mat(BLACK, rough=0.28, coat=0.55)
def gold(): return mat(GOLD, metal=1, rough=0.2)
def glass(): return mat('#1E2229', rough=0.04, coat=1.0)

def link(o, parent=None, m=None):
    if o.name not in bpy.context.scene.collection.objects: bpy.context.scene.collection.objects.link(o)
    if parent: o.parent = parent
    if m:
        o.data.materials.clear(); o.data.materials.append(m)
    return o

def empty(name, parent=None, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None); link(e, parent); e.location = loc; return e

def bevel(o, w=0.05, seg=4):
    b = o.modifiers.new('Bevel', 'BEVEL'); b.width = w; b.segments = seg; b.limit_method = 'ANGLE'
    return o

def smooth(o):
    for p in o.data.polygons: p.use_smooth = True
    return o

def prim(kind, parent=None, m=None, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), **kw):
    getattr(bpy.ops.mesh, 'primitive_%s_add' % kind)(**kw)
    o = bpy.context.object
    bpy.context.scene.collection.objects.link(o) if o.name not in bpy.context.scene.collection.objects else None
    o.location = loc; o.rotation_euler = [math.radians(r) for r in rot]; o.scale = scale
    if parent: o.parent = parent
    if m: o.data.materials.append(m)
    return o

def box(parent, m, loc, size, bev=0.06):
    o = prim('cube', parent, m, loc, scale=(size[0] / 2, size[1] / 2, size[2] / 2))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return bevel(o, bev, 5) if bev else o

def extrude_poly(pts, depth, parent=None, m=None, bev=0.04, name='poly', holes=()):
    """Polygone 2D (x, z) extrudé sur l'axe Y, centré en Y."""
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    vs = [bm.verts.new((x, -depth / 2, z)) for x, z in pts]
    f = bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=[f])
    if f.normal.y > 0: f.normal_flip()
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    nv = [g for g in r['geom'] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=nv, vec=(0, depth, 0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); link(o, parent, m)
    if bev: bevel(o, bev, 4)
    return o

def text3d(body, parent, m, size=1.0, extrude=0.18, bev=0.03, loc=(0, 0, 0)):
    cu = bpy.data.curves.new('T', 'FONT'); cu.body = body
    cu.font = bpy.data.fonts.load(FONT, check_existing=True)
    cu.size = size; cu.extrude = extrude; cu.bevel_depth = bev; cu.bevel_resolution = 3
    cu.align_x = 'CENTER'; cu.align_y = 'CENTER'
    o = bpy.data.objects.new('T', cu); link(o, parent)
    o.data.materials.append(m)
    o.rotation_euler = (math.radians(90), 0, 0); o.location = loc
    return o

def check_mark(parent, m, s=1.0, loc=(0, 0, 0), depth=0.15):
    pts = [(-0.55, 0.05), (-0.35, 0.25), (-0.12, 0.02), (0.38, 0.52), (0.58, 0.32), (-0.12, -0.38)]
    o = extrude_poly([(x * s, z * s) for x, z in pts], depth, parent, m, bev=0.02 * s, name='check')
    o.location = loc; return o

class Anim:
    """Collecte des fonctions d'animation par image, puis pose des keyframes sur chaque image."""
    def __init__(self, n): self.n = n; self.fns = []
    def on(self, fn): self.fns.append(fn); return fn
    def bake(self, objs):
        for f in range(1, self.n + 1):
            for fn in self.fns: fn(f)
            for o in objs:
                o.keyframe_insert('location', frame=f); o.keyframe_insert('rotation_euler', frame=f)
                o.keyframe_insert('scale', frame=f)
        for o in objs:
            if o.animation_data and o.animation_data.action:
                try:
                    for fc in o.animation_data.action.fcurves:
                        for k in fc.keyframe_points: k.interpolation = 'LINEAR'
                except AttributeError:
                    pass

def pop_scale(f, start, dur=12, end=None, out_dur=8):
    s = ease_out_back(lin(f, start, start + dur))
    if end is not None: s *= 1 - ease_in(lin(f, end - out_dur, end))
    return max(s, 0.0001)

# ---------------------------------------------------------------- éléments

def house(parent, loc, s=1.0):
    h = empty('house', parent, loc)
    box(h, mat(WHITE, rough=0.4), (0, 0, 0), (1.6 * s, 1.3 * s, 1.2 * s), 0.05)
    roof = extrude_poly([(-1.05 * s, 0.55 * s), (1.05 * s, 0.55 * s), (0, 1.45 * s)], 1.5 * s, h, blk(), 0.05, 'roof')
    box(h, blk(), (0.45 * s, 0, 1.25 * s), (0.25 * s, 0.25 * s, 0.6 * s), 0.03)  # cheminée
    box(h, blk(), (0, -0.66 * s, -0.25 * s), (0.42 * s, 0.1 * s, 0.7 * s), 0.04)      # porte
    prim('uv_sphere', h, mat(GOLD, 1, 0.2), (0.12 * s, -0.72 * s, -0.25 * s), scale=(0.04 * s,) * 3)
    for x in (-0.55, 0.55):
        box(h, glass(), (x * s, -0.66 * s, 0.15 * s), (0.34 * s, 0.08 * s, 0.34 * s), 0.03)
    return h

def badge_check(parent, loc, s=0.55):
    b = empty('badge', parent, loc)
    d = prim('cylinder', b, gold(), (0, 0, 0), (90, 0, 0), vertices=64, radius=s, depth=0.16 * s / 0.55)
    bevel(d, 0.04, 4); smooth(d)
    check_mark(b, mat(WHITE), s * 0.85, (0, -0.12 * s / 0.55, 0), 0.12)
    return b

def el_houses(samples):
    """3 maisons « signées » qui tombent une par une avec rebond, puis un badge ✓ sur chacune."""
    N = 105; sc = reset(800, 560, samples, cam_dist=11.5, lens=55, cam_z=0.8)
    root = empty('root'); objs = [root]
    hs, bs = [], []
    for i, x in enumerate((-2.3, 0, 2.3)):
        pivot = empty('pv%d' % i, root, (x, 0, -0.6)); hs.append(pivot)
        house(pivot, (0, 0, 0.6), s=0.95 if i != 1 else 1.1)
        b = badge_check(pivot, (0.75, -0.9, 1.8), 0.38); bs.append(b)
        objs += [pivot, b]
    starts = (1, 9, 17)
    a = Anim(N)
    @a.on
    def _(f):
        root.rotation_euler = (0, 0, math.radians(18 * math.sin(f / 30 * 1.3)))
        root.location = (0, 0, 0.12 * math.sin(f / 30 * 2.4))
        for i, p in enumerate(hs):
            st = starts[i]
            fall = lin(f, st, st + 16)
            p.location.z = -0.6 + 7 * (1 - bounce(fall))
            sq = 1 - 0.18 * math.exp(-max(0, f - st - 9) / 3) * (f > st + 9)
            p.scale = (1 / math.sqrt(max(sq, .1)), 1, sq) if f > st + 9 else (1, 1, 1)
            p.scale = tuple(v * (1 - ease_in(lin(f, N - 8, N))) + 1e-4 for v in p.scale)
            bs[i].scale = (pop_scale(f, 40 + 7 * i, 12),) * 3
            bs[i].rotation_euler = (0, math.radians(360 * (1 - ease_out(lin(f, 40 + 7 * i, 58 + 7 * i)))), 0)
    a.bake(objs)
    return N

def el_play(samples):
    """Bouton lecture 3D qui arrive en tournoyant + compteur « 1 500 » + « VIDÉOS »."""
    N = 105; sc = reset(900, 560, samples, cam_dist=13, lens=55)
    root = empty('root'); btn = empty('btn', root, (0, 0, 0.9))
    b = box(btn, blk(), (0, 0, 0), (2.9, 0.7, 2.0), 0.45); b.modifiers['Bevel'].segments = 8
    extrude_poly([(-0.42, -0.55), (-0.42, 0.55), (0.62, 0)], 0.3, btn, gold(), 0.06, 'tri').location = (0.05, -0.38, 0)
    cnt = text3d('0', root, gold(), 1.35, 0.22, 0.03, (0, 0, -1.35))
    lab = text3d('VIDÉOS YOUTUBE', root, blk(), 0.5, 0.12, 0.015, (0, 0, -2.35))
    a = Anim(N)
    @a.on
    def _(f):
        s = pop_scale(f, 1, 16, N, 9)
        btn.scale = (s,) * 3
        btn.rotation_euler = (math.radians(10 * math.sin(f / 12)), 0, math.radians(-360 * (1 - ease_out(lin(f, 1, 26))) + 14 * math.sin(f / 17)))
        cnt.scale = (pop_scale(f, 22, 10, N, 9),) * 3
        lab.scale = (pop_scale(f, 34, 10, N, 9),) * 3
        cnt.rotation_euler = (math.radians(90), math.radians(4 * math.sin(f / 9)), math.radians(8 * math.sin(f / 20)))
        lab.rotation_euler = (math.radians(90), 0, math.radians(8 * math.sin(f / 20)))
    a.bake([root, btn, cnt, lab])
    # compteur : 0 → 1 500 entre les images 22 et 45 (« 1500 » est prononcé à ~10.4 s)
    def body(f):
        v = int(round(1500 * ease_out(lin(f, 22, 45)) / 10) * 10)
        return '+' + ('{:,}'.format(v).replace(',', ' '))
    return N, (cnt, body)

def el_question(samples):
    N = 60; sc = reset(420, 460, samples, cam_dist=7.5, lens=55)
    root = empty('root')
    q = text3d('?', root, gold(), 3.3, 0.45, 0.06)
    a = Anim(N)
    @a.on
    def _(f):
        root.scale = (pop_scale(f, 1, 14, N, 8),) * 3
        root.rotation_euler = (0, math.radians(-8 + 10 * math.sin(f / 7)), math.radians(360 * (1 - ease_out(lin(f, 1, 24))) + 20 * math.sin(f / 10)))
        root.location.z = 0.25 * math.sin(f / 6)
    a.bake([root]); return N

def key3d(parent, loc, s=1.0):
    k = empty('key', parent, loc)
    g = mat(GOLD, metal=1, rough=0.18)
    t = prim('torus', k, g, (0, 0, 0), (90, 0, 0), major_radius=0.45 * s, minor_radius=0.13 * s, major_segments=48, minor_segments=16); smooth(t)
    c = prim('cylinder', k, g, (1.05 * s, 0, 0), (0, 90, 0), vertices=32, radius=0.1 * s, depth=1.3 * s); smooth(c)
    box(k, g, (1.45 * s, 0, -0.2 * s), (0.14 * s, 0.14 * s, 0.35 * s), 0.02)
    box(k, g, (1.2 * s, 0, -0.16 * s), (0.12 * s, 0.14 * s, 0.26 * s), 0.02)
    return k

def el_suitcase(samples):
    """Valise (voyageurs de courte durée) + clé dorée en orbite."""
    N = 90; sc = reset(620, 560, samples, cam_dist=12, lens=55)
    root = empty('root'); sc_ = empty('case', root, (0, 0, -0.2))
    body = box(sc_, blk(), (0, 0, 0), (2.4, 1.0, 1.9), 0.22)
    for x in (-0.6, 0.6): box(sc_, gold(), (x, 0, 0), (0.28, 1.08, 1.95), 0.05)
    h = prim('torus', sc_, mat('#2B2B2B', rough=0.5), (0, 0, 1.05), (90, 0, 0), major_radius=0.45, minor_radius=0.1); smooth(h)
    for x in (-0.8, 0.8):
        w = prim('cylinder', sc_, mat('#222222'), (x, 0, -1.08), (90, 0, 0), vertices=24, radius=0.14, depth=0.25); smooth(w)
    orbit = empty('orbit', root, (0, 0, 0.1)); k = key3d(orbit, (2.0, 0, 0), 0.8)
    a = Anim(N)
    @a.on
    def _(f):
        root.scale = (pop_scale(f, 1, 15, N, 9),) * 3
        sc_.rotation_euler = (0, math.radians(5 * math.sin(f / 8)), math.radians(-25 + 30 * ease_out(lin(f, 1, 30)) + 10 * math.sin(f / 22)))
        orbit.rotation_euler = (math.radians(12), math.radians(-15), math.radians(-f * 6.5))
        k.rotation_euler = (math.radians(f * 7), 0, 0)
    a.bake([root, sc_, orbit, k]); return N

def el_coins(samples):
    """Pile de pièces d'or qui monte + grand « % » orange."""
    N = 100; sc = reset(520, 640, samples, cam_dist=9.5, lens=55, cam_z=-0.1)
    root = empty('root'); coins = []
    g = mat(GOLD, metal=1, rough=0.22)
    for i in range(8):
        c = prim('cylinder', root, g, (-0.15, 0, -2.2 + i * 0.3), (0, 0, 0), vertices=48, radius=0.95, depth=0.24)
        bevel(c, 0.05, 3); smooth(c); coins.append(c)
    pct = text3d('%', root, blk(), 2.0, 0.35, 0.05, (1.0, -1.2, 1.2))
    a = Anim(N)
    starts = [1 + i * 3 for i in range(8)]
    @a.on
    def _(f):
        root.rotation_euler = (math.radians(14), 0, math.radians(20 * math.sin(f / 25)))
        out = 1 - ease_in(lin(f, N - 8, N))
        for i, c in enumerate(coins):
            z0 = -2.2 + i * 0.3
            c.location = (-0.15 + 0.05 * math.sin(i * 1.7), 0, z0 + 6 * (1 - bounce(lin(f, starts[i], starts[i] + 11))))
            c.rotation_euler = (math.radians(4 * math.sin(i * 2.1)), 0, math.radians(f * 4 + i * 30))
            c.scale = (out + 1e-4,) * 3
        pct.scale = (pop_scale(f, 28, 14, N, 8),) * 3
        pct.rotation_euler = (math.radians(90), math.radians(-360 * (1 - ease_out(lin(f, 28, 50)))), math.radians(-12 + 8 * math.sin(f / 9)))
    a.bake([root, pct] + coins); return N

def cursor(parent, s=1.0):
    pts = [(0, 0), (0, -1.55), (0.36, -1.2), (0.62, -1.78), (0.86, -1.67), (0.6, -1.1), (1.08, -1.1)]
    c = empty('cursor', parent)
    extrude_poly([(x * s, z * s) for x, z in pts], 0.22 * s, c, mat(WHITE, rough=0.3), 0.03 * s, 'cur')
    back = [(x * 1.13 - 0.07, z * 1.1 + 0.1) for x, z in pts]
    o = extrude_poly([(x * s, z * s) for x, z in back], 0.14 * s, c, blk(), 0.02 * s, 'curb'); o.location.y = 0.08 * s
    return c

def el_cursor(samples):
    """Curseur 3D qui glisse et clique (le clic tombe à l'image 25)."""
    N = 60; sc = reset(420, 460, samples, cam_dist=10, lens=55)
    root = empty('root'); c = cursor(root, 1.6)
    a = Anim(N)
    @a.on
    def _(f):
        x = 2.4 * (1 - ease_out(lin(f, 1, 18)))
        press = math.exp(-((f - 25) / 2.5) ** 2)
        root.location = (x - 0.6, 0, 1.2 + 1.3 * (1 - ease_out(lin(f, 1, 18))))
        root.scale = (max(1e-4, (1 - 0.25 * press) * (1 - ease_in(lin(f, N - 7, N)))),) * 3
        root.rotation_euler = (math.radians(-25 * press + 12), math.radians(-12), math.radians(-15 + 6 * math.sin(f / 9)))
    a.bake([root]); return N

def el_gift(samples):
    """Cadeau (masterclass gratuite) : le couvercle saute à l'image 38 (« 100 % »)."""
    N = 70; sc = reset(460, 560, samples, cam_dist=11, lens=55, cam_z=0.4)
    root = empty('root'); base = empty('base', root)
    box(base, blk(), (0, 0, -0.5), (2.0, 2.0, 1.6), 0.06)
    for r in (0, 90):
        o = box(base, gold(), (0, 0, -0.5), (0.35, 2.06, 1.62) if r == 0 else (2.06, 0.35, 1.62), 0.03)
    lid = empty('lid', root, (0, 0, 0.3))
    box(lid, blk(), (0, 0, 0.15), (2.2, 2.2, 0.4), 0.06)
    box(lid, gold(), (0, 0, 0.15), (0.37, 2.24, 0.42), 0.03); box(lid, gold(), (0, 0, 0.15), (2.24, 0.37, 0.42), 0.03)
    for r in (-40, 40):
        t = prim('torus', lid, gold(), (0.35 * (1 if r > 0 else -1), 0, 0.6), (90, r, 0), major_radius=0.38, minor_radius=0.11); smooth(t)
        t.scale = (1, 0.6, 1)
    tr = empty('tr'); txt = text3d('GRATUIT', tr, gold(), 0.75, 0.16, 0.025, (0, -2.2, 0.9))
    a = Anim(N)
    @a.on
    def _(f):
        out = 1 - ease_in(lin(f, N - 8, N))
        root.scale = (max(1e-4, pop_scale(f, 1, 14) * out),) * 3
        root.rotation_euler = (math.radians(18), 0, math.radians(35 + 12 * math.sin(f / 14)))
        op = ease_out_elastic(lin(f, 36, 60))
        lid.location = (0, 0, 0.3 + 1.1 * op); lid.rotation_euler = (math.radians(-18 * op), math.radians(14 * op), 0)
        txt.scale = (max(1e-4, pop_scale(f, 38, 12)),) * 3
        txt.location = (0, -2.2, -0.2 + 2.6 * ease_out(lin(f, 38, 52)))
        txt.scale = (max(1e-4, pop_scale(f, 38, 12) * out),) * 3
        txt.rotation_euler = (math.radians(90), 0, math.radians(6 * math.sin(f / 8)))
    a.bake([root, lid, txt]); return N

def gear_pts(teeth, r_out, r_in, n_per=6):
    pts = []
    for i in range(teeth):
        a0 = 2 * math.pi * i / teeth; step = 2 * math.pi / teeth
        for j, (fr, rr) in enumerate([(0.0, r_in), (0.18, r_in), (0.3, r_out), (0.62, r_out), (0.74, r_in)]):
            a = a0 + fr * step; pts.append((rr * math.cos(a), rr * math.sin(a)))
    return pts

def el_gears(samples):
    """Engrenages qui s'emboîtent (« comment ton activité peut fonctionner »)."""
    N = 85; sc = reset(760, 520, samples, cam_dist=13, lens=55)
    root = empty('root')
    g1 = empty('g1', root, (-1.2, 0, 0)); g2 = empty('g2', root, (1.45, 0, -0.35)); g3 = empty('g3', root, (0.9, 0, 1.75))
    for g, t, r, is_gold in ((g1, 14, 1.55, False), (g2, 10, 1.1, True), (g3, 8, 0.85, False)):
        o = extrude_poly(gear_pts(t, r, r * 0.8), 0.45, g, gold() if is_gold else blk(), 0.03, 'gear')
        h = prim('cylinder', g, blk() if is_gold else gold(), (0, -0.05, 0), (90, 0, 0), vertices=48, radius=r * 0.3, depth=0.62); smooth(h)
        bevel(h, 0.03, 3)
    a = Anim(N)
    @a.on
    def _(f):
        root.scale = (pop_scale(f, 1, 15, N, 9),) * 3
        root.rotation_euler = (math.radians(-10), 0, math.radians(18 * math.sin(f / 26)))
        sp = 4.0 * ease_out(lin(f, 4, 30)) + 1
        g1.rotation_euler = (0, math.radians(f * sp), 0)
        g2.rotation_euler = (0, math.radians(-f * sp * 14 / 10 + 18), 0)
        g3.rotation_euler = (0, math.radians(-f * sp * 14 / 8 + 7), 0)
    a.bake([root, g1, g2, g3]); return N

def el_shield(samples):
    """Bouclier « résultats garantis » avec coche."""
    N = 60; sc = reset(460, 520, samples, cam_dist=11, lens=55)
    root = empty('root')
    pts = []
    for i in range(33):
        t = i / 32; x = -1.3 + 2.6 * t
        pts.append((x, 1.4 + 0.18 * math.sin(math.pi * t)))
    for i in range(1, 32):
        t = i / 32; a = math.pi * t
        x = 1.3 * math.cos(a) if False else 1.3 - 2.6 * t
        z = 1.4 - 1.6 * (1 - (2 * abs(t - 0.5)) ** 2.2) - 1.6 * (0.5 - abs(t - 0.5)) * 1.25
        pts.append((x, z))
    pts2 = [(1.3, 1.4)] + [(1.3 * (1 - t) ** 0.8 * (1 if True else 0), 1.4 - 3.0 * t ** 1.3) for t in [i / 24 for i in range(1, 25)]]
    right = [(1.3 * math.cos(t * math.pi / 2) ** 0.7, 0.6 - 2.0 * math.sin(t * math.pi / 2)) for t in [i / 24 for i in range(25)]]
    top = [(-1.3 + 2.6 * t, 1.4 + 0.15 * math.sin(math.pi * t)) for t in [i / 16 for i in range(17)]]
    left = [(-x, z) for x, z in reversed(right)]
    outline = top + [(1.3, 1.0)] + right[1:] + left[1:-1] + [(-1.3, 1.0)]
    outline = [p for i, p in enumerate(outline) if i == 0 or (abs(p[0] - outline[i - 1][0]) + abs(p[1] - outline[i - 1][1])) > 1e-3]
    sh = empty('sh', root)
    extrude_poly(outline, 0.4, sh, gold(), 0.06, 'shield')
    inner = [(x * 0.82, 0.2 + (z - 0.2) * 0.82) for x, z in outline]
    o = extrude_poly(inner, 0.2, sh, blk(), 0.04, 'shin'); o.location.y = -0.2
    check_mark(sh, mat(WHITE), 1.3, (0, -0.35, 0.05), 0.2)
    a = Anim(N)
    @a.on
    def _(f):
        root.scale = (pop_scale(f, 1, 14, N, 8),) * 3
        root.rotation_euler = (0, 0, math.radians(-360 * (1 - ease_out(lin(f, 1, 26))) + 15 * math.sin(f / 11)))
        root.location.z = 0.12 * math.sin(f / 8)
    a.bake([root]); return N

def el_rocket(samples):
    """Fusée (« nouveau lancement ») avec flamme émissive vacillante ; le déplacement se fait au compositing."""
    N = 45; sc = reset(420, 640, samples, cam_dist=12, lens=55)
    root = empty('root'); r = empty('rk', root)
    prof = [(0.0, 2.2), (0.3, 1.95), (0.55, 1.5), (0.7, 0.9), (0.74, 0.2), (0.7, -0.5), (0.6, -1.1), (0.45, -1.3), (0.0, -1.3)]
    me = bpy.data.meshes.new('body'); bm = bmesh.new(); seg = 48
    rings = []
    for x, z in prof:
        rings.append([bm.verts.new((x * math.cos(2 * math.pi * k / seg), x * math.sin(2 * math.pi * k / seg), z)) for k in range(seg)])
    for a_, b_ in zip(rings, rings[1:]):
        for k in range(seg):
            try: bm.faces.new((a_[k], a_[(k + 1) % seg], b_[(k + 1) % seg], b_[k]))
            except ValueError: pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free()
    body = bpy.data.objects.new('body', me); link(body, r, mat(WHITE, rough=0.3)); smooth(body)
    nose = prim('uv_sphere', r, blk(), (0, 0, 1.92), segments=48, ring_count=24, radius=0.36); smooth(nose)
    nose.scale = (1, 1, 1.0)
    win = prim('torus', r, gold(), (0, -0.66, 0.75), (90, 0, 0), major_radius=0.3, minor_radius=0.07); smooth(win)
    gl = prim('uv_sphere', r, glass(), (0, -0.62, 0.75), radius=0.27); smooth(gl); gl.scale = (1, 0.35, 1)
    for ang in (0, 120, 240):
        piv = empty('fp', r); piv.rotation_euler = (0, 0, math.radians(ang + 90))
        extrude_poly([(0.5, -0.4), (1.25, -1.45), (1.2, -1.75), (0.55, -1.2)], 0.12, piv, blk(), 0.03, 'fin').rotation_euler = (0, 0, math.radians(0))
    fl = prim('cone', r, mat('#FFB02E', emit=18), (0, 0, -2.05), (180, 0, 0), vertices=32, radius1=0.42, depth=1.4); smooth(fl)
    fl2 = prim('cone', r, mat('#FFF1C4', emit=30), (0, 0, -1.8), (180, 0, 0), vertices=32, radius1=0.24, depth=0.8); smooth(fl2)
    a = Anim(N)
    @a.on
    def _(f):
        r.rotation_euler = (math.radians(8), 0, math.radians(f * 9))
        k = 1 + 0.25 * math.sin(f * 2.3) + 0.15 * math.sin(f * 5.1)
        fl.scale = (1, 1, k); fl.location.z = -1.3 - 0.7 * k
        fl2.scale = (1, 1, k); fl2.location.z = -1.3 - 0.4 * k
    a.bake([r, fl, fl2]); return N

ELEMENTS = dict(houses=el_houses, play=el_play, question=el_question, suitcase=el_suitcase, coins=el_coins,
                cursor=el_cursor, gift=el_gift, gears=el_gears, shield=el_shield, rocket=el_rocket)

def main():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    name, out = args[0], args[1]
    samples = int(args[2]) if len(args) > 2 else 24
    only = int(args[3]) if len(args) > 3 else None     # rendre une seule image (aperçu)
    threads = int(args[4]) if len(args) > 4 else 0
    res = ELEMENTS[name](samples)
    N, dyn = (res if isinstance(res, tuple) else (res, None))
    sc = bpy.context.scene
    if threads: sc.render.threads_mode = 'FIXED'; sc.render.threads = threads
    os.makedirs(out, exist_ok=True)
    frames = [only] if only else range(1, N + 1)
    for f in frames:
        p = os.path.join(out, '%s_%04d.png' % (name, f))
        if os.path.exists(p) and not only: continue
        sc.frame_set(f)
        if dyn: dyn[0].data.body = dyn[1](f)
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
    print('DONE', name, N)

if __name__ == '__main__':
    main()
