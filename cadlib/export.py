"""Writers for native FreeCAD (.FCStd), STEP AP214 and STL."""
import os

import FreeCAD as App
import MeshPart


def fcstd(path, objects, params, label):
    """Native FreeCAD document: one Part::Feature per solid plus a Parameters spreadsheet
    documenting the inputs the model was generated from."""
    doc = App.newDocument(label.replace(" ", "_"))
    sheet = doc.addObject("Spreadsheet::Sheet", "Parameters")
    sheet.set("A1", "parameter")
    sheet.set("B1", "value")
    row = 2
    for key, value in flatten(params):
        sheet.set(f"A{row}", key)
        sheet.set(f"B{row}", str(value) if not isinstance(value, (int, float)) else f"{value:g}")
        row += 1
    for name, (shape, rgb) in objects.items():
        obj = doc.addObject("Part::Feature", name.replace(" ", "_"))
        obj.Label = name
        obj.Shape = shape
    doc.recompute()
    if os.path.exists(path):
        os.remove(path)  # avoid FreeCAD's .FCBak backup copies on regeneration
    doc.saveAs(path)
    App.closeDocument(doc.Name)


def step(path, shape):
    shape.exportStep(path)


def stl(path, shape, deflection=0.02):
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=deflection, AngularDeflection=0.2, Relative=False)
    mesh.write(path)
    return mesh.CountFacets


def flatten(d, prefix=""):
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            yield from flatten(v, key + ".")
        elif isinstance(v, list) and v and isinstance(v[0], list):
            for i, item in enumerate(v):
                yield f"{key}[{i}]", item
        else:
            yield key, v
