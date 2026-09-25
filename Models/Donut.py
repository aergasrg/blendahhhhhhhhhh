"""Builds a frosted donut with sprinkles, saves .blend/.glb and renders a preview.

Run: python3 Models/Donut.py   (needs `pip install bpy`)
"""
import math
import os
import random

import bpy

OutputDir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Output")
ModelName = "Donut"

# Tweak these to change the donut
MajorRadius = 1.0
MinorRadius = 0.42
SprinkleCount = 120
RandomSeed = 7


def ClearScene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def MakeMaterial(Name, Color, Roughness=0.5):
    Mat = bpy.data.materials.new(Name)
    Mat.use_nodes = True
    Bsdf = Mat.node_tree.nodes["Principled BSDF"]
    Bsdf.inputs["Base Color"].default_value = (*Color, 1.0)
    Bsdf.inputs["Roughness"].default_value = Roughness
    return Mat


def BuildDough():
    bpy.ops.mesh.primitive_torus_add(
        major_radius=MajorRadius, minor_radius=MinorRadius,
        major_segments=64, minor_segments=32,
    )
    Dough = bpy.context.active_object
    Dough.name = "Dough"
    Dough.data.materials.append(MakeMaterial("DoughMat", (0.72, 0.45, 0.2), 0.7))
    bpy.ops.object.shade_smooth()
    return Dough


def BuildIcing(Dough):
    # Copy the top half of the dough, push it outward a bit = icing
    Icing = Dough.copy()
    Icing.data = Dough.data.copy()
    Icing.name = "Icing"
    bpy.context.collection.objects.link(Icing)
    Mesh = Icing.data
    Rng = random.Random(RandomSeed)
    for Vert in Mesh.vertices:
        if Vert.co.z < -0.05 + Rng.uniform(-0.06, 0.06):
            Vert.co.z = -10  # mark for deletion
    bpy.context.view_layer.objects.active = Icing
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    for Vert in Mesh.vertices:
        Vert.select = Vert.co.z < -5
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.delete(type="VERT")
    bpy.ops.object.mode_set(mode="OBJECT")
    Solid = Icing.modifiers.new("Thickness", "SOLIDIFY")
    Solid.thickness = 0.04
    Solid.offset = 1
    Icing.modifiers.new("Smooth", "SUBSURF").levels = 1
    Icing.data.materials.clear()
    Icing.data.materials.append(MakeMaterial("IcingMat", (0.95, 0.4, 0.65), 0.25))
    return Icing


def BuildSprinkles():
    Rng = random.Random(RandomSeed)
    Colors = [(1, 1, 1), (0.1, 0.5, 1), (1, 0.85, 0.1), (0.2, 0.85, 0.3), (0.9, 0.15, 0.15)]
    Mats = [MakeMaterial(f"Sprinkle{I}", C, 0.4) for I, C in enumerate(Colors)]
    for I in range(SprinkleCount):
        Theta = Rng.uniform(0, 2 * math.pi)
        Phi = Rng.uniform(0.15, math.pi - 0.15)  # top half of the tube
        Ring = MajorRadius + (MinorRadius + 0.045) * math.cos(Phi)
        X, Y = Ring * math.cos(Theta), Ring * math.sin(Theta)
        Z = (MinorRadius + 0.045) * math.sin(Phi)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=0.08, vertices=8, location=(X, Y, Z))
        Sprinkle = bpy.context.active_object
        Sprinkle.name = f"Sprinkle{I}"
        Sprinkle.rotation_euler = (Rng.uniform(1.2, 1.9), 0, Rng.uniform(0, 2 * math.pi))
        Sprinkle.data.materials.append(Rng.choice(Mats))


def SetupRender():
    Scene = bpy.context.scene
    bpy.ops.object.camera_add(location=(0, -4.6, 3.7), rotation=(math.radians(52), 0, 0))
    Scene.camera = bpy.context.active_object
    bpy.ops.object.light_add(type="AREA", location=(2, -2, 4))
    bpy.context.active_object.data.energy = 600
    bpy.context.active_object.data.size = 3
    World = bpy.data.worlds.new("World")
    World.use_nodes = True
    World.node_tree.nodes["Background"].inputs["Color"].default_value = (0.9, 0.85, 0.8, 1)
    World.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6
    Scene.world = World
    Scene.render.engine = "CYCLES"
    Scene.cycles.samples = 64
    Scene.cycles.device = "CPU"
    Scene.render.resolution_x = 800
    Scene.render.resolution_y = 600


def Main():
    ClearScene()
    Dough = BuildDough()
    BuildIcing(Dough)
    BuildSprinkles()
    SetupRender()
    os.makedirs(OutputDir, exist_ok=True)
    BasePath = os.path.abspath(os.path.join(OutputDir, ModelName))
    bpy.ops.wm.save_as_mainfile(filepath=BasePath + ".blend")
    bpy.ops.export_scene.gltf(filepath=BasePath + ".glb")
    bpy.context.scene.render.filepath = BasePath + ".png"
    bpy.ops.render.render(write_still=True)
    print("Built", BasePath)


if __name__ == "__main__":
    Main()
