"""Builds a realistic blue glass-cleaner trigger spray bottle, saves .blend/.glb and renders a preview.

Run: python3 Models/SprayBottle.py   (needs `pip install bpy pillow`)
Quick preview: RenderSamples=32 ResolutionPercent=50 python3 Models/SprayBottle.py

All dimensions are in meters (bottle is ~27 cm tall, like a real 23 oz bottle).
"""
import math
import os

import bpy
import bmesh  # only importable after bpy
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OutputDir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Output"))
ModelName = "SprayBottle"

RenderSamples = int(os.environ.get("RenderSamples", 128))
ResolutionPercent = int(os.environ.get("ResolutionPercent", 100))

# Bottle body profile keys: (Height, HalfWidth, HalfDepth, Squareness)
# Squareness 2 = ellipse, higher = boxier rounded rectangle.
BodyProfile = [
    (0.0000, 0.0400, 0.0255, 3.0),
    (0.0035, 0.0462, 0.0302, 3.0),
    (0.0120, 0.0476, 0.0312, 3.0),
    (0.1100, 0.0476, 0.0312, 3.0),
    (0.1340, 0.0442, 0.0296, 3.0),  # grip waist
    (0.1560, 0.0472, 0.0311, 3.0),
    (0.1660, 0.0458, 0.0304, 2.8),
    (0.1780, 0.0360, 0.0262, 2.4),  # shoulder
    (0.1880, 0.0215, 0.0190, 2.1),
    (0.1940, 0.0155, 0.0155, 2.0),  # neck
    (0.1968, 0.0155, 0.0155, 2.0),
    (0.1975, 0.0178, 0.0178, 2.0),  # support ring
    (0.2000, 0.0178, 0.0178, 2.0),
    (0.2007, 0.0145, 0.0145, 2.0),
    (0.2160, 0.0145, 0.0145, 2.0),
]
BodySegments = 128
WallThickness = 0.0008
LiquidGap = 0.0012
LiquidLevel = 0.160
PuntHeight = 0.004  # the dome pushed up into the bottom

LabelBottom = 0.022
LabelTop = 0.108
LabelHalfAngle = 1.15  # radians either side of the front
LabelBrand = "CLARITY"

# Sprayer head profile along Y (front is -Y): (Y, CenterZ, HalfWidth, HalfHeight)
ShroudProfile = [
    (0.0240, 0.2410, 0.0090, 0.0120),
    (0.0205, 0.2406, 0.0145, 0.0165),
    (0.0110, 0.2400, 0.0158, 0.0175),
    (0.0000, 0.2398, 0.0152, 0.0165),
    (-0.0200, 0.2400, 0.0135, 0.0135),
    (-0.0400, 0.2404, 0.0118, 0.0108),
    (-0.0510, 0.2402, 0.0110, 0.0098),
    (-0.0555, 0.2402, 0.0090, 0.0080),
]
TriggerPath = [(-0.0290, 0.2330), (-0.0355, 0.2230), (-0.0405, 0.2110),
               (-0.0425, 0.1990), (-0.0408, 0.1880), (-0.0365, 0.1820)]

WhitePlasticColor = (0.90, 0.91, 0.93)
AccentPlasticColor = (0.02, 0.22, 0.72)
LiquidColor = (0.02, 0.55, 1.0)


# ---------- math helpers ----------

def PchipTable(Xs, Ys):
    """Monotone cubic (Fritsch-Carlson) interpolator: no overshoot, so profiles stay clean."""
    Count = len(Xs)
    Deltas = [(Ys[I + 1] - Ys[I]) / (Xs[I + 1] - Xs[I]) for I in range(Count - 1)]
    Slopes = [Deltas[0]] + [0.0] * (Count - 2) + [Deltas[-1]]
    for I in range(1, Count - 1):
        if Deltas[I - 1] * Deltas[I] > 0:
            W1 = 2 * (Xs[I + 1] - Xs[I]) + (Xs[I] - Xs[I - 1])
            W2 = (Xs[I + 1] - Xs[I]) + 2 * (Xs[I] - Xs[I - 1])
            Slopes[I] = (W1 + W2) / (W1 / Deltas[I - 1] + W2 / Deltas[I])

    def Evaluate(X):
        X = min(max(X, Xs[0]), Xs[-1])
        I = max(0, min(Count - 2, next((J for J in range(Count - 1) if X <= Xs[J + 1]), Count - 2)))
        Span = Xs[I + 1] - Xs[I]
        T = (X - Xs[I]) / Span
        H00, H10 = 2 * T**3 - 3 * T**2 + 1, T**3 - 2 * T**2 + T
        H01, H11 = -2 * T**3 + 3 * T**2, T**3 - T**2
        return H00 * Ys[I] + H10 * Span * Slopes[I] + H01 * Ys[I + 1] + H11 * Span * Slopes[I + 1]

    return Evaluate


def ProfileSampler(Keys):
    Keys = sorted(Keys)  # interpolator needs increasing X
    Xs = [Key[0] for Key in Keys]
    Channels = [PchipTable(Xs, [Key[C] for Key in Keys]) for C in range(1, len(Keys[0]))]
    return lambda X: [Channel(X) for Channel in Channels]


def Superellipse(Theta, HalfA, HalfB, Squareness):
    Cos, Sin = math.cos(Theta), math.sin(Theta)
    Power = 2.0 / Squareness
    return (HalfA * math.copysign(abs(Cos) ** Power, Cos), HalfB * math.copysign(abs(Sin) ** Power, Sin))


def CatmullRom(Points, Samples):
    Pts = [Points[0]] + list(Points) + [Points[-1]]
    Result = []
    for S in range(Samples):
        U = S / (Samples - 1) * (len(Points) - 1)
        I = min(int(U), len(Points) - 2)
        T = U - I
        P0, P1, P2, P3 = (Vector(P) for P in Pts[I:I + 4])
        Result.append(0.5 * ((2 * P1) + (-P0 + P2) * T + (2 * P0 - 5 * P1 + 4 * P2 - P3) * T**2
                             + (-P0 + 3 * P1 - 3 * P2 + P3) * T**3))
    return Result


# ---------- mesh helpers ----------

def LoftRings(Name, Rings, StartCap=None, EndCap=None, Closed=True, Uvs=None, FixNormals=True):
    """Skin a list of vertex rings into quads, with optional fan caps at the ends."""
    Bm = bmesh.new()
    VertRings = [[Bm.verts.new(P) for P in Ring] for Ring in Rings]
    UvLayer = Bm.loops.layers.uv.new("UVMap") if Uvs else None
    Width = len(Rings[0]) if Closed else len(Rings[0]) - 1
    for R in range(len(VertRings) - 1):
        A, B = VertRings[R], VertRings[R + 1]
        for I in range(Width):
            J = (I + 1) % len(A)
            Face = Bm.faces.new((A[I], A[J], B[J], B[I]))
            if UvLayer:
                for Loop, (Ri, Vi) in zip(Face.loops, ((R, I), (R, J), (R + 1, J), (R + 1, I))):
                    Loop[UvLayer].uv = Uvs[Ri][Vi]
    for Cap, Ring in ((StartCap, VertRings[0]), (EndCap, VertRings[-1])):
        if Cap is not None:
            Center = Bm.verts.new(Cap)
            for I in range(len(Ring)):
                Bm.faces.new((Ring[I], Ring[(I + 1) % len(Ring)], Center))
    if FixNormals:
        bmesh.ops.recalc_face_normals(Bm, faces=Bm.faces)
    Mesh = bpy.data.meshes.new(Name)
    Bm.to_mesh(Mesh)
    Bm.free()
    Mesh.shade_smooth()
    Obj = bpy.data.objects.new(Name, Mesh)
    bpy.context.collection.objects.link(Obj)
    return Obj


def BodyHeights():
    # Dense uniform sampling plus every key height so sharp features stay crisp
    Heights = {round(I * 0.0012, 5) for I in range(int(BodyProfile[-1][0] / 0.0012) + 1)}
    Heights |= {Key[0] for Key in BodyProfile}
    return sorted(H for H in Heights if H <= BodyProfile[-1][0])


def BodyRing(Sample, Height, Inset=0.0, Segments=BodySegments):
    HalfWidth, HalfDepth, Squareness = Sample(Height)
    Ring = []
    for S in range(Segments):
        X, Y = Superellipse(2 * math.pi * S / Segments, HalfWidth - Inset, HalfDepth - Inset, Squareness)
        Ring.append((X, Y, Height))
    return Ring


# ---------- materials ----------

def NewMaterial(Name):
    Mat = bpy.data.materials.new(Name)
    Mat.use_nodes = True
    return Mat, Mat.node_tree.nodes, Mat.node_tree.links, Mat.node_tree.nodes["Principled BSDF"]


def PlasticMaterial(Name, Color, Roughness):
    Mat, Nodes, Links, Bsdf = NewMaterial(Name)
    Bsdf.inputs["Base Color"].default_value = (*Color, 1)
    Bsdf.inputs["Roughness"].default_value = Roughness
    Bsdf.inputs["Subsurface Weight"].default_value = 0.15  # soft, slightly translucent plastic
    Bsdf.inputs["Subsurface Radius"].default_value = (0.004, 0.004, 0.004)
    Bsdf.inputs["Subsurface Scale"].default_value = 1.0
    # Micro-texture so highlights break up like molded plastic
    Noise = Nodes.new("ShaderNodeTexNoise")
    Noise.inputs["Scale"].default_value = 900
    Bump = Nodes.new("ShaderNodeBump")
    Bump.inputs["Strength"].default_value = 0.03
    Links.new(Noise.outputs["Fac"], Bump.inputs["Height"])
    Links.new(Bump.outputs["Normal"], Bsdf.inputs["Normal"])
    return Mat


def ClearPetMaterial():
    Mat, Nodes, Links, Bsdf = NewMaterial("ClearPET")
    Bsdf.inputs["Base Color"].default_value = (0.97, 0.99, 1.0, 1)
    Bsdf.inputs["Transmission Weight"].default_value = 1.0
    Bsdf.inputs["Roughness"].default_value = 0.015
    Bsdf.inputs["IOR"].default_value = 1.57
    return Mat


def LiquidMaterial():
    Mat, Nodes, Links, Bsdf = NewMaterial("CleanerLiquid")
    Bsdf.inputs["Base Color"].default_value = (0.85, 0.95, 1.0, 1)
    Bsdf.inputs["Transmission Weight"].default_value = 1.0
    Bsdf.inputs["Roughness"].default_value = 0.0
    Bsdf.inputs["IOR"].default_value = 1.333
    # Color comes from absorption through the volume, so thick parts get deeper blue
    Absorb = Nodes.new("ShaderNodeVolumeAbsorption")
    Absorb.inputs["Color"].default_value = (*LiquidColor, 1)
    Absorb.inputs["Density"].default_value = 70.0
    Links.new(Absorb.outputs["Volume"], Nodes["Material Output"].inputs["Volume"])
    return Mat


def LabelMaterial(ImagePath):
    Mat, Nodes, Links, Bsdf = NewMaterial("Label")
    Tex = Nodes.new("ShaderNodeTexImage")
    Tex.image = bpy.data.images.load(ImagePath)
    Tex.interpolation = "Cubic"
    Bsdf.inputs["Roughness"].default_value = 0.22
    Bsdf.inputs["Coat Weight"].default_value = 0.25  # glossy laminated label
    Bsdf.inputs["Coat Roughness"].default_value = 0.05
    # Back of the label (seen through the bottle) is plain white paper
    Geometry = Nodes.new("ShaderNodeNewGeometry")
    BackMix = Nodes.new("ShaderNodeMix")
    BackMix.data_type = "RGBA"
    BackMix.inputs["B"].default_value = (0.85, 0.85, 0.85, 1)
    Links.new(Geometry.outputs["Backfacing"], BackMix.inputs["Factor"])
    Links.new(Tex.outputs["Color"], BackMix.inputs["A"])
    Links.new(BackMix.outputs["Result"], Bsdf.inputs["Base Color"])
    # Rounded corners via alpha
    Links.new(Tex.outputs["Alpha"], Bsdf.inputs["Alpha"])
    return Mat


def FlatMaterial(Name, Color, Roughness=0.5):
    Mat, Nodes, Links, Bsdf = NewMaterial(Name)
    Bsdf.inputs["Base Color"].default_value = (*Color, 1)
    Bsdf.inputs["Roughness"].default_value = Roughness
    return Mat


# ---------- label artwork ----------

def FindFont(Names, Size):
    Dirs = ["/usr/share/fonts/truetype/freefont", "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation", "/Library/Fonts", "C:/Windows/Fonts"]
    for Name in Names:
        for Dir in Dirs:
            Path = os.path.join(Dir, Name)
            if os.path.exists(Path):
                return ImageFont.truetype(Path, Size)
    return ImageFont.load_default(size=Size)


def CenteredText(Draw, Center, Text, Font, Fill, Shadow=None):
    Box = Draw.textbbox((0, 0), Text, font=Font)
    Pos = (Center[0] - (Box[2] - Box[0]) / 2 - Box[0], Center[1] - (Box[3] - Box[1]) / 2 - Box[1])
    if Shadow:
        Draw.text((Pos[0] + 6, Pos[1] + 8), Text, font=Font, fill=Shadow)
    Draw.text(Pos, Text, font=Font, fill=Fill)


def DrawLabel(Path, Width, Height):
    Img = Image.new("RGBA", (Width, Height))
    Draw = ImageDraw.Draw(Img)
    for Y in range(Height):  # deep-to-bright blue gradient
        T = Y / Height
        Draw.line([(0, Y), (Width, Y)], fill=(int(4 + 10 * T), int(40 + 80 * T), int(130 + 95 * T), 255))

    # Glossy highlight swoosh and white wave band
    Glow = Image.new("RGBA", Img.size)
    ImageDraw.Draw(Glow).ellipse([-Width * 0.3, -Height * 0.55, Width * 1.3, Height * 0.42], fill=(255, 255, 255, 45))
    Img.alpha_composite(Glow.filter(ImageFilter.GaussianBlur(140)))
    Wave = [(X, Height * 0.60 + math.sin(X / Width * 2 * math.pi) * Height * 0.035) for X in range(0, Width + 1, 8)]
    WaveLow = [(X, Height * 0.80 + math.sin(X / Width * 2 * math.pi + 0.6) * Height * 0.03) for X in range(Width, -1, -8)]
    Draw.polygon(Wave + WaveLow, fill=(248, 250, 255, 255))
    Draw.line(Wave, fill=(120, 200, 255, 255), width=14)

    BrandFont = FindFont(["FreeSansBoldOblique.ttf", "DejaVuSans-BoldOblique.ttf", "LiberationSans-BoldItalic.ttf"], int(Height * 0.24))
    TagFont = FindFont(["FreeSansOblique.ttf", "DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf"], int(Height * 0.07))
    TypeFont = FindFont(["FreeSansBold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"], int(Height * 0.085))
    SizeFont = FindFont(["FreeSansBold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"], int(Height * 0.05))

    CenteredText(Draw, (Width / 2, Height * 0.25), LabelBrand, BrandFont, (255, 255, 255, 255), Shadow=(0, 20, 70, 160))
    PillW, PillH = Width * 0.58, Height * 0.1
    Draw.rounded_rectangle([Width / 2 - PillW / 2, Height * 0.43 - PillH / 2, Width / 2 + PillW / 2, Height * 0.43 + PillH / 2],
                           radius=PillH / 2, fill=(255, 214, 40, 255))
    CenteredText(Draw, (Width / 2, Height * 0.43), "Streak-Free Shine", TagFont, (10, 50, 130, 255))
    CenteredText(Draw, (Width / 2, Height * 0.705), "GLASS CLEANER", TypeFont, (8, 55, 150, 255))
    CenteredText(Draw, (Width / 2, Height * 0.91), "23 FL OZ (680 mL)", SizeFont, (255, 255, 255, 255))

    # Thin border stripes plus rounded-corner alpha mask
    Draw.rectangle([0, 0, Width, Height * 0.018], fill=(120, 200, 255, 255))
    Draw.rectangle([0, Height * 0.982, Width, Height], fill=(120, 200, 255, 255))
    Mask = Image.new("L", Img.size, 0)
    ImageDraw.Draw(Mask).rounded_rectangle([0, 0, Width - 1, Height - 1], radius=int(Height * 0.06), fill=255)
    Img.putalpha(Mask)
    Img.save(Path)


# ---------- parts ----------

def BuildBottle(Sample):
    Heights = BodyHeights()
    Rings = [BodyRing(Sample, H) for H in Heights]
    Bottle = LoftRings("Bottle", Rings, StartCap=(0, 0, PuntHeight))
    Solid = Bottle.modifiers.new("Wall", "SOLIDIFY")
    Solid.thickness = WallThickness
    Solid.offset = -1
    Solid.use_even_offset = True
    Bottle.data.materials.append(ClearPetMaterial())
    return Bottle


def BuildLiquid(Sample):
    Heights = [H for H in BodyHeights() if 0.0014 < H < LiquidLevel] + [LiquidLevel]
    Rings = [BodyRing(Sample, H, Inset=LiquidGap) for H in Heights]
    Liquid = LoftRings("Liquid", Rings, StartCap=(0, 0, PuntHeight + LiquidGap), EndCap=(0, 0, LiquidLevel))
    Liquid.data.materials.append(LiquidMaterial())
    return Liquid


def BuildLabel(Sample):
    Offset = 0.0003
    Columns = 96
    Heights = [LabelBottom + (LabelTop - LabelBottom) * I / 40 for I in range(41)]
    Thetas = [-math.pi / 2 - LabelHalfAngle + 2 * LabelHalfAngle * I / (Columns - 1) for I in range(Columns)]
    Rings = []
    for H in Heights:
        HalfWidth, HalfDepth, Squareness = Sample(H)
        Rings.append([(*Superellipse(T, HalfWidth + Offset, HalfDepth + Offset, Squareness), H) for T in Thetas])
    # U by arc length so the artwork is not stretched on the flatter front
    MidRing = Rings[len(Rings) // 2]
    Arc = [0.0]
    for A, B in zip(MidRing, MidRing[1:]):
        Arc.append(Arc[-1] + (Vector(B) - Vector(A)).length)
    Uvs = [[(Arc[I] / Arc[-1], R / (len(Rings) - 1)) for I in range(Columns)] for R in range(len(Rings))]

    ImageWidth = 2048
    ImageHeight = int(ImageWidth * (LabelTop - LabelBottom) / Arc[-1])
    TexPath = os.path.join(OutputDir, "Textures", "SprayBottleLabel.png")
    os.makedirs(os.path.dirname(TexPath), exist_ok=True)
    DrawLabel(TexPath, ImageWidth, ImageHeight)

    Label = LoftRings("Label", Rings, Closed=False, Uvs=Uvs, FixNormals=False)
    Label.data.materials.append(LabelMaterial(TexPath))
    return Label


def BuildCollar(Material):
    Radius, Ribs = 0.0186, 90
    Segments = Ribs * 4
    Rings = []
    for Z, Inset, Ribbed in ((0.1995, 0.0012, False), (0.2003, 0.0003, False), (0.2012, 0, True),
                             (0.2168, 0, True), (0.2177, 0.0003, False), (0.2183, 0.0012, False)):
        Ring = []
        for S in range(Segments):
            Theta = 2 * math.pi * S / Segments
            R = Radius - Inset + (0.00045 * max(0.0, math.cos(Ribs * Theta)) if Ribbed else 0)
            Ring.append((R * math.cos(Theta), R * math.sin(Theta), Z))
        Rings.append(Ring)
    Collar = LoftRings("Collar", Rings, StartCap=(0, 0, 0.1995), EndCap=(0, 0, 0.2186))
    Collar.data.materials.append(Material)
    return Collar


def BuildShroud(Material):
    Sample = ProfileSampler(ShroudProfile)
    Ys = [ShroudProfile[0][0] + (ShroudProfile[-1][0] - ShroudProfile[0][0]) * I / 79 for I in range(80)]
    Rings = []
    for Y in Ys:
        CenterZ, HalfWidth, HalfHeight = Sample(Y)
        Rings.append([(X, Y, CenterZ + Z) for X, Z in
                      (Superellipse(2 * math.pi * S / 96, HalfWidth, HalfHeight, 3.6) for S in range(96))])
    Shroud = LoftRings("Shroud", Rings,
                       StartCap=(0, Ys[0] + 0.0012, Sample(Ys[0])[0]), EndCap=(0, Ys[-1] - 0.0008, Sample(Ys[-1])[0]))
    Shroud.data.materials.append(Material)

    # Pump housing that joins shroud to collar
    Rings = [[(0.0098 * math.cos(A), 0.0098 * math.sin(A) + 0.004, Z) for A in (2 * math.pi * S / 48 for S in range(48))]
             for Z in (0.2180, 0.2270)]
    Pump = LoftRings("PumpHousing", Rings, EndCap=(0, 0.004, 0.2270))
    Pump.data.materials.append(Material)
    return Shroud


def BuildNozzle(Material, DarkMaterial):
    Front = ShroudProfile[-1][0]
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0045, depth=0.006, vertices=32,
                                        location=(0, Front - 0.002, 0.2402), rotation=(math.pi / 2, 0, 0))
    Stem = bpy.context.active_object
    Stem.name = "NozzleStem"
    Stem.data.materials.append(Material)

    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, Front - 0.0085, 0.2402))
    Cap = bpy.context.active_object
    Cap.name = "NozzleCap"
    Cap.scale = (0.0135, 0.0075, 0.0135)
    bpy.ops.object.transform_apply(scale=True)
    Bevel = Cap.modifiers.new("Bevel", "BEVEL")
    Bevel.width = 0.0022
    Bevel.segments = 5
    Cap.modifiers.new("Smooth", "SUBSURF").levels = 1
    Cap.data.materials.append(Material)
    Cap.data.shade_smooth()

    bpy.ops.mesh.primitive_cylinder_add(radius=0.0009, depth=0.001, vertices=24,
                                        location=(0, Front - 0.0123, 0.2402), rotation=(math.pi / 2, 0, 0))
    Orifice = bpy.context.active_object
    Orifice.name = "Orifice"
    Orifice.data.materials.append(DarkMaterial)
    return Cap


def BuildTrigger(Material):
    Path = CatmullRom(TriggerPath, 48)
    Rings = []
    for I, Point in enumerate(Path):
        Tangent = (Path[min(I + 1, len(Path) - 1)] - Path[max(I - 1, 0)]).normalized()
        Normal = Vector((-Tangent.y, Tangent.x))  # perpendicular in the YZ plane
        T = I / (len(Path) - 1)
        HalfWidth = 0.0078 + 0.0016 * math.sin(T * math.pi)
        HalfThickness = 0.0030 + 0.0010 * math.sin(T * math.pi)
        Ring = []
        for S in range(40):
            X, N = Superellipse(2 * math.pi * S / 40, HalfWidth, HalfThickness, 4.0)
            Ring.append((X, Point.x + Normal.x * N, Point.y + Normal.y * N))
        Rings.append(Ring)
    Trigger = LoftRings("Trigger", Rings, StartCap=(0, *Path[0]), EndCap=(0, *Path[-1]))
    Trigger.modifiers.new("Smooth", "SUBSURF").levels = 1
    Trigger.data.materials.append(Material)
    return Trigger


def BuildDipTube():
    Path = CatmullRom([(0, 0.004, 0.220), (0, 0.003, 0.14), (0.001, -0.002, 0.05),
                       (0.004, -0.010, 0.012), (0.006, -0.016, PuntHeight + 0.004)], 60)
    Rings = []
    for I, Point in enumerate(Path):
        Tangent = (Path[min(I + 1, len(Path) - 1)] - Path[max(I - 1, 0)]).normalized()
        Side = Tangent.cross(Vector((1, 0, 0))).normalized()
        Up = Tangent.cross(Side).normalized()
        Rings.append([tuple(Point + 0.0021 * (math.cos(A) * Side + math.sin(A) * Up))
                      for A in (2 * math.pi * S / 16 for S in range(16))])
    Tube = LoftRings("DipTube", Rings, StartCap=tuple(Path[0]), EndCap=tuple(Path[-1]))
    Mat, Nodes, Links, Bsdf = NewMaterial("DipTube")
    Bsdf.inputs["Base Color"].default_value = (0.95, 0.97, 1.0, 1)
    Bsdf.inputs["Transmission Weight"].default_value = 0.85
    Bsdf.inputs["Roughness"].default_value = 0.25
    Tube.data.materials.append(Mat)
    return Tube


# ---------- studio ----------

def BuildStudio():
    # Seamless cyclorama sweep: floor that curves up into a back wall
    Profile = [(Y, 0.0) for Y in (-2.0, -0.5, 0.0, 0.25)]
    Profile += [(0.25 + 0.5 * math.sin(A), 0.5 - 0.5 * math.cos(A)) for A in (math.pi / 2 * I / 24 for I in range(1, 25))]
    Profile += [(0.75, 2.0)]
    Rows = [[(X, Y, Z) for X in (-2.0 + 4.0 * I / 8 for I in range(9))] for Y, Z in Profile]
    Sweep = LoftRings("Cyclorama", Rows, Closed=False, FixNormals=False)
    if Sweep.data.polygons[0].normal.z < 0:
        Sweep.data.flip_normals()
    Mat, Nodes, Links, Bsdf = NewMaterial("Backdrop")
    Bsdf.inputs["Base Color"].default_value = (0.82, 0.84, 0.87, 1)
    Bsdf.inputs["Roughness"].default_value = 0.32
    Sweep.data.materials.append(Mat)

    # Black flags beside the bottle: invisible to camera, but they give the clear plastic
    # its crisp dark edge lines in refraction (a classic product-photography trick)
    Black = FlatMaterial("Flag", (0.005, 0.005, 0.005), 0.9)
    for Side in (-1, 1):
        bpy.ops.mesh.primitive_plane_add(size=1, location=(0.28 * Side, 0.18, 0.2),
                                         rotation=(math.pi / 2, 0, math.radians(90 - 25 * Side)))
        Flag = bpy.context.active_object
        Flag.name = f"Flag{'Left' if Side < 0 else 'Right'}"
        Flag.scale = (0.35, 0.6, 1)
        Flag.visible_camera = False
        Flag.data.materials.append(Black)

    def AddArea(Name, Location, Target, Power, SizeX, SizeY, Color=(1, 1, 1)):
        Data = bpy.data.lights.new(Name, "AREA")
        Data.shape = "RECTANGLE"
        Data.size, Data.size_y = SizeX, SizeY
        Data.energy = Power
        Data.color = Color
        Light = bpy.data.objects.new(Name, Data)
        bpy.context.collection.objects.link(Light)
        Light.location = Location
        Light.rotation_euler = (Vector(Target) - Vector(Location)).to_track_quat("-Z", "Y").to_euler()
        Light.visible_camera = False
        return Light

    AddArea("KeySoftbox", (-0.55, -0.45, 0.55), (0, 0, 0.13), 14, 0.5, 0.7, (1.0, 0.97, 0.93))
    AddArea("RimStrip", (0.45, 0.35, 0.35), (0, 0, 0.15), 12, 0.12, 0.7, (0.92, 0.96, 1.0))
    AddArea("BackdropGlow", (0.0, 0.12, 0.12), (0, 0.8, 0.3), 5, 0.15, 0.15)  # lights the wall behind so the liquid glows
    AddArea("TopFill", (0.1, -0.1, 0.8), (0, 0, 0), 4, 0.6, 0.6)

    World = bpy.data.worlds.new("World")
    World.use_nodes = True
    World.node_tree.nodes["Background"].inputs["Color"].default_value = (0.6, 0.62, 0.66, 1)
    World.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25
    bpy.context.scene.world = World


def SetupCamera():
    Target = bpy.data.objects.new("CameraTarget", None)
    bpy.context.collection.objects.link(Target)
    Target.location = (0, 0, 0.128)
    CamData = bpy.data.cameras.new("Camera")
    CamData.lens = 85
    CamData.dof.use_dof = True
    CamData.dof.focus_object = Target
    CamData.dof.aperture_fstop = 8
    Cam = bpy.data.objects.new("Camera", CamData)
    bpy.context.collection.objects.link(Cam)
    Cam.location = (-0.32, -0.78, 0.2)
    Track = Cam.constraints.new("TRACK_TO")
    Track.target = Target
    Track.track_axis = "TRACK_NEGATIVE_Z"
    Track.up_axis = "UP_Y"
    bpy.context.scene.camera = Cam


def SetupRender():
    Scene = bpy.context.scene
    Scene.render.engine = "CYCLES"
    Scene.cycles.device = "CPU"
    Scene.cycles.samples = RenderSamples
    Scene.cycles.use_denoising = True
    Scene.cycles.max_bounces = 32
    Scene.cycles.transmission_bounces = 32
    Scene.cycles.transparent_max_bounces = 32
    Scene.cycles.glossy_bounces = 8
    Scene.cycles.volume_bounces = 2
    Scene.cycles.blur_glossy = 0.5
    Scene.render.resolution_x = 1080
    Scene.render.resolution_y = 1350
    Scene.render.resolution_percentage = ResolutionPercent
    Scene.view_settings.view_transform = "AgX"
    Scene.view_settings.look = "AgX - Punchy"


def Main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OutputDir, exist_ok=True)
    Sample = ProfileSampler(BodyProfile)
    White = PlasticMaterial("WhitePlastic", WhitePlasticColor, 0.3)
    Accent = PlasticMaterial("AccentPlastic", AccentPlasticColor, 0.28)
    Dark = FlatMaterial("Dark", (0.01, 0.01, 0.012), 0.6)

    BuildBottle(Sample)
    BuildLiquid(Sample)
    BuildLabel(Sample)
    BuildDipTube()
    BuildCollar(White)
    BuildShroud(White)
    BuildNozzle(Accent, Dark)
    BuildTrigger(Accent)
    BuildStudio()
    SetupCamera()
    SetupRender()

    BasePath = os.path.join(OutputDir, ModelName)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=BasePath + ".blend")
    ExportNames = {"Bottle", "Liquid", "Label", "DipTube", "Collar", "Shroud", "PumpHousing",
                   "NozzleStem", "NozzleCap", "Orifice", "Trigger"}
    bpy.ops.object.select_all(action="DESELECT")
    for Obj in bpy.data.objects:
        Obj.select_set(Obj.name in ExportNames)
    bpy.ops.export_scene.gltf(filepath=BasePath + ".glb", use_selection=True)
    bpy.context.scene.render.filepath = BasePath + ".png"
    bpy.ops.render.render(write_still=True)
    print("Built", BasePath)


if __name__ == "__main__":
    Main()
