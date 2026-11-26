#!/usr/bin/env pvpython
"""Render one CFD image from an OpenFOAM case.

FIELD       U      velocity magnitude on a slice
            p      kinematic pressure (p/rho) on a slice
            psurf  kinematic pressure on the aircraft surface (3D view)
SLICE_AXIS  x | y | z   slice plane normal (ignored for psurf)
              z = top view of the mid-height plane, y = side view of the mid-span plane
ZOOM        body (default) frames the aircraft and its wake; full shows the whole domain
"""

from paraview.simple import *
import os

CASE_FILE = os.getenv("CASE_FILE", "/workspace/results/aircraft/case.foam")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data")
FIELD = os.getenv("FIELD", "U")
SLICE_AXIS = os.getenv("SLICE_AXIS", "z").lower()
ZOOM = os.getenv("ZOOM", "body").lower()

IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080
ASPECT = IMAGE_WIDTH / IMAGE_HEIGHT


def log(message):
    print(message, flush=True)


def latest_time_of(reader):
    times = reader.TimestepValues
    # pvpython returns a bare float when there is only one timestep
    if isinstance(times, (int, float)):
        times = [times]
    times = list(times)
    return max(times) if times else 0


def find_body_region(reader):
    """Name of the aircraft patch in the reader's mesh regions, or None."""
    try:
        names = list(reader.MeshRegions.Available)
    except Exception:
        return None
    for name in names:
        if name.lower().endswith("aircraft"):
            return name
    return None


def main():
    log("=== ParaView CFD visualization ===")

    if not os.path.exists(CASE_FILE):
        raise FileNotFoundError(f"OpenFOAM case not found: {CASE_FILE}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    axis = SLICE_AXIS if SLICE_AXIS in ("x", "y", "z") else "z"
    if axis != SLICE_AXIS:
        log(f"Unknown SLICE_AXIS '{SLICE_AXIS}', using z")
    field = FIELD if FIELD in ("U", "p", "psurf") else "U"
    if field != FIELD:
        log(f"Unknown FIELD '{FIELD}', using U")

    # ---- Volume data -------------------------------------------------
    reader = OpenFOAMReader(registrationName="AircraftCFD", FileName=CASE_FILE)
    reader.MeshRegions = ["internalMesh"]
    reader.CellArrays = ["U", "p"]
    reader.UpdatePipeline()
    latest = latest_time_of(reader)
    log(f"Latest timestep: {latest}")
    reader.UpdatePipeline(time=latest)

    # ---- Aircraft surface (optional but wanted for context/psurf) ----
    body = None
    try:
        region = find_body_region(reader)
        if region:
            body = OpenFOAMReader(registrationName="AircraftSurface", FileName=CASE_FILE)
            body.MeshRegions = [region]
            body.CellArrays = ["p"]
            body.UpdatePipeline(time=latest)
            log(f"Aircraft surface region: {region}")
        else:
            log("Aircraft surface region not found; showing the volume only")
    except Exception as error:  # noqa: BLE001
        body = None
        log(f"Could not load aircraft surface: {error}")

    if field == "psurf" and body is None:
        raise RuntimeError("psurf needs the aircraft surface, which could not be loaded")

    # ---- View --------------------------------------------------------
    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = [IMAGE_WIDTH, IMAGE_HEIGHT]
    view.Background = [0.08, 0.09, 0.13]
    view.UseColorPaletteForBackground = 0

    # Use the latest solution for every pipeline object and the screenshot.
    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    scene.AnimationTime = latest
    view.ViewTime = latest

    # Body bounds (for framing)
    if body is not None:
        bb = body.GetDataInformation().GetBounds()
    else:
        bb = reader.GetDataInformation().GetBounds()
    cx, cy, cz = [(bb[0] + bb[1]) / 2, (bb[2] + bb[3]) / 2, (bb[4] + bb[5]) / 2]
    bx, by, bz = bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4]
    size = max(bx, by, bz)

    # ---- Surface pressure view --------------------------------------
    if field == "psurf":
        display = Show(body, view)
        display.Representation = "Surface"
        ColorBy(display, ("CELLS", "p"))
        lut = GetColorTransferFunction("p")
        lut.ApplyPreset("Cool to Warm", True)
        display.RescaleTransferFunctionToDataRange(True, False)
        display.SetScalarBarVisibility(view, True)
        bar = GetScalarBar(lut, view)
        bar.Title = "Surface kinematic pressure p/rho [m^2/s^2]"
        bar.ComponentTitle = ""

        view.CameraParallelProjection = 0
        d = 2.2 * size
        view.CameraFocalPoint = [cx, cy, cz]
        view.CameraPosition = [cx - d, cy - 1.2 * d, cz + 0.8 * d]
        view.CameraViewUp = [0, 0, 1]
        view.ResetCamera()
        Render()
        out = os.path.join(OUTPUT_DIR, f"{CASE_NAME()}_psurf.png")
        SaveScreenshot(out, view, ImageResolution=[IMAGE_WIDTH, IMAGE_HEIGHT])
        log(f"Screenshot saved: {out}")
        log("=== SUCCESS ===")
        return

    # ---- Slice view -------------------------------------------------
    slice_filter = Slice(registrationName="FlowSlice", Input=reader)
    slice_filter.SliceType = "Plane"
    slice_filter.SliceType.Normal = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[axis]
    slice_filter.SliceType.Origin = [0, 0, 0]
    slice_filter.UpdatePipeline(time=latest)

    display = Show(slice_filter, view)
    display.Representation = "Surface"

    if field == "p":
        ColorBy(display, ("CELLS", "p"))
        lut = GetColorTransferFunction("p")
        title = "Kinematic pressure p/rho [m^2/s^2]"
    else:
        ColorBy(display, ("CELLS", "U", "Magnitude"))
        lut = GetColorTransferFunction("U")
        title = "Velocity magnitude [m/s]"
    lut.ApplyPreset("Cool to Warm", True)
    display.LookupTable = lut
    display.RescaleTransferFunctionToDataRange(True, False)
    display.SetScalarBarVisibility(view, True)
    bar = GetScalarBar(lut, view)
    bar.Title = title
    bar.ComponentTitle = ""

    if body is not None:
        body_display = Show(body, view)
        body_display.Representation = "Surface"
        ColorBy(body_display, None)
        body_display.AmbientColor = [0.15, 0.15, 0.15]
        body_display.DiffuseColor = [0.15, 0.15, 0.15]

    # ---- Camera ------------------------------------------------------
    view.CameraParallelProjection = 1
    if axis == "z":      # top view: X right, Y up
        view.CameraFocalPoint = [cx + 0.8 * bx, cy, 0]
        view.CameraPosition = [cx + 0.8 * bx, cy, 100 * size]
        view.CameraViewUp = [0, 1, 0]
        horiz, vert = bx, by
    elif axis == "y":    # side view: X right, Z up
        view.CameraFocalPoint = [cx + 0.8 * bx, 0, cz]
        view.CameraPosition = [cx + 0.8 * bx, -100 * size, cz]
        view.CameraViewUp = [0, 0, 1]
        horiz, vert = bx, bz
    else:                # front view along X: Y right, Z up
        view.CameraFocalPoint = [0, cy, cz]
        view.CameraPosition = [-100 * size, cy, cz]
        view.CameraViewUp = [0, 0, 1]
        horiz, vert = by, bz

    if ZOOM == "full":
        view.ResetCamera()
    else:
        # Show about 3 body-widths horizontally; keep the aspect ratio.
        half_h = max(vert * 1.2, horiz * 3.0 / ASPECT / 2.0, 0.25 * size)
        view.CameraParallelScale = half_h

    Render()
    out = os.path.join(OUTPUT_DIR, f"{CASE_NAME()}_{field}_{axis}.png")
    SaveScreenshot(out, view, ImageResolution=[IMAGE_WIDTH, IMAGE_HEIGHT])
    log(f"Screenshot saved: {out}")
    log("=== SUCCESS ===")


def CASE_NAME():
    # .../results/<case>/case.foam -> <case>
    return os.path.basename(os.path.dirname(CASE_FILE)) or "aircraft"


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log(f"ERROR: {error}")
        raise
