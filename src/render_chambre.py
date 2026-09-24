"""Chambre photoréaliste (lit blanc, oreillers, tête de lit en tissu, rideaux légers, lumière de fenêtre).

Usage : python3 render_chambre.py <sortie.png> [samples] [largeur] [hauteur]
Sert de fond « photo » aux cartes (style de la vidéo de référence).
"""
import bpy, bmesh, math, sys, os
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render3d as R
from render3d import mat, prim, smooth

def soft_box(name, loc, size, subdiv=3, puff=0.0, m=None):
    """Cube subdivisé et « gonflé » (coussins, matelas, couette)."""
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.object; o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    b = o.modifiers.new('bev', 'BEVEL'); b.width = min(size) * 0.22; b.segments = 5
    s = o.modifiers.new('sub', 'SUBSURF'); s.levels = subdiv; s.render_levels = subdiv
    if puff:   # « gonflement » : on bombe les faces avant/arrière au lieu d'un modificateur Cast (qui décale l'objet)
        o.scale = (1, 1 + puff, 1)
    smooth(o)
    if m: o.data.materials.append(m)
    return o

def fabric(col, rough=0.85, sheen=0.6):
    m = bpy.data.materials.new('fab'); m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = R.srgb(col); p.inputs['Roughness'].default_value = rough
    p.inputs['Sheen Weight'].default_value = sheen
    # léger grain de tissu
    nt = m.node_tree; n = nt.nodes.new('ShaderNodeTexNoise'); n.inputs['Scale'].default_value = 400
    bm = nt.nodes.new('ShaderNodeBump'); bm.inputs['Strength'].default_value = 0.08
    nt.links.new(n.outputs['Fac'], bm.inputs['Height']); nt.links.new(bm.outputs['Normal'], p.inputs['Normal'])
    return m

def main():
    out = sys.argv[1]; samples = int(sys.argv[2]) if len(sys.argv) > 2 else 96
    rx = int(sys.argv[3]) if len(sys.argv) > 3 else 1080; ry = int(sys.argv[4]) if len(sys.argv) > 4 else 1920
    sc = R.reset(rx, ry, samples)
    sc.render.film_transparent = False
    sc.cycles.max_bounces = 6; sc.cycles.diffuse_bounces = 4
    sc.view_settings.view_transform = 'AgX'
    try: sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception: pass
    sc.view_settings.exposure = -0.9
    for o in list(bpy.data.objects):
        if o.type == 'LIGHT': bpy.data.objects.remove(o)
    w = sc.world; w.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.25

    wall = mat('#E4DDD1', rough=0.9, coat=0)
    floor = mat('#A98C6C', rough=0.65, coat=0.05)
    # pièce
    prim('plane', None, floor, (0, 0, 0), size=30)
    back = prim('plane', None, wall, (0, 2.2, 3), (90, 0, 0), size=30)
    left = prim('plane', None, wall, (-3.4, 0, 3), (0, 90, 0), size=30)
    # lit
    linen = fabric('#F6F4EF', 0.9, 0.4); head = fabric('#B9AC98', 0.95, 0.8); duvet = fabric('#FBFAF7', 0.92, 0.5)
    soft_box('frame', (0, 0.2, 0.25), (3.3, 4.2, 0.5), 2, 0, fabric('#CFC6B6', 0.9, 0.6))
    soft_box('mattress', (0, 0.2, 0.68), (3.2, 4.1, 0.45), 3, 0, linen)
    soft_box('headboard', (0, 2.1, 1.35), (3.6, 0.3, 1.9), 3, 0, head)
    d = soft_box('duvet', (0, -0.55, 0.95), (3.4, 2.7, 0.22), 3, 0, duvet)
    for x, rot in ((-0.8, -3), (0.8, 4)):
        p = soft_box('pillow', (x, 1.6, 1.25), (1.35, 0.34, 0.72), 3, 0.3, linen)
        p.rotation_euler = (math.radians(-22), 0, math.radians(rot))
    p = soft_box('cushion', (0.05, 1.25, 1.12), (1.0, 0.26, 0.5), 3, 0.3, fabric('#8FAE9A', 0.9, 0.7))
    p.rotation_euler = (math.radians(-15), 0, math.radians(-2))
    # plaid replié au pied du lit
    soft_box('plaid', (0, -1.45, 1.06), (3.36, 0.75, 0.12), 3, 0, fabric('#C9BBA3', 0.95, 0.8))
    # table de chevet + lampe
    soft_box('nightstand', (2.35, 1.6, 0.4), (0.8, 0.7, 0.8), 2, 0, mat('#B89B78', rough=0.5, coat=0.2))
    lamp = prim('uv_sphere', None, mat('#FFF3DC', emit=3.0), (2.35, 1.65, 1.1), radius=0.22); smooth(lamp)
    # grande baie derrière le lit, voilée par des rideaux légers : la lumière du jour les traverse
    back.location.y = 3.2
    for x0 in (-2.6, -0.9, 0.9, 2.6):
        # rideau = grille fine dont on ondule les sommets (vrais plis verticaux)
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=160, y_subdivisions=6, size=1, location=(x0, 2.75, 2.9), rotation=(math.radians(90), 0, 0))
        c = bpy.context.object; c.scale = (1.9, 5.8, 1)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        ph = x0 * 1.7
        for v in c.data.vertices:
            x = v.co.x
            v.co.z += 0.07 * math.sin(x * 14 + ph) + 0.03 * math.sin(x * 31 + 2 * ph)
        s_ = c.modifiers.new('sub', 'SUBSURF'); s_.levels = 1; s_.render_levels = 2
        smooth(c)
        m = bpy.data.materials.new('voile'); m.use_nodes = True
        pb = m.node_tree.nodes['Principled BSDF']
        pb.inputs['Base Color'].default_value = R.srgb('#FBF8F2'); pb.inputs['Roughness'].default_value = 0.8
        pb.inputs['Transmission Weight'].default_value = 0.0
        pb.inputs['Subsurface Weight'].default_value = 0.0
        pb.inputs['Alpha'].default_value = 0.93
        pb.inputs['Sheen Weight'].default_value = 0.5
        tr = m.node_tree.nodes.new('ShaderNodeBsdfTranslucent'); tr.inputs['Color'].default_value = R.srgb('#FFF6E8')
        mix = m.node_tree.nodes.new('ShaderNodeMixShader'); mix.inputs['Fac'].default_value = 0.45
        outn = m.node_tree.nodes['Material Output']
        m.node_tree.links.new(pb.outputs['BSDF'], mix.inputs[1]); m.node_tree.links.new(tr.outputs['BSDF'], mix.inputs[2])
        m.node_tree.links.new(mix.outputs['Shader'], outn.inputs['Surface'])
        c.data.materials.append(m)
    # lumière du jour derrière les rideaux + fenêtre latérale douce
    R.light('Baie', (0, 3.05, 3.0), 1800, 7, '#FFF4E4')
    bpy.data.objects['Baie'].rotation_euler = (math.radians(-90), 0, 0)
    R.light('Fenetre', (-3.2, 0.3, 2.8), 350, 4.5, '#FFF1DE')
    L = bpy.data.objects['Fenetre']; L.rotation_euler = (0, math.radians(-90), 0)
    R.light('Remplissage', (2.5, -7, 3.5), 160, 6, '#F4F6FF')
    sun = bpy.data.lights.new('Soleil', 'SUN'); sun.energy = 0.8; sun.angle = math.radians(8); sun.color = R.srgb('#FFE7C4')[:3]
    so = bpy.data.objects.new('Soleil', sun); sc.collection.objects.link(so); so.rotation_euler = (math.radians(60), math.radians(-55), math.radians(-20))
    # caméra à hauteur d'œil, légère plongée, focale douce avec profondeur de champ
    cam = sc.camera
    if os.environ.get('CADRAGE') == 'serre':
        cam.location = (-0.9, -2.6, 1.55); cam.data.lens = 50; tgt = Vector((-0.2, 1.5, 1.2))
    else:
        cam.location = (0.35, -6.4, 1.75); cam.data.lens = 36; tgt = Vector((0.1, 1.2, 1.45)); cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.dof.use_dof = True; cam.data.dof.focus_distance = (tgt - cam.location).length; cam.data.dof.aperture_fstop = 2.8
    sc.render.use_motion_blur = False
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print('DONE', out)

if __name__ == '__main__':
    main()
