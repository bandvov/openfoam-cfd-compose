#!/usr/bin/env pvpython
"""Render one CFD image from an OpenFOAM case.

FIELD       U      velocity magnitude on a slice
            p      kinematic pressure (p/rho) on a slice
            psurf  kinematic pressure on the aircraft surface (3D view)
            streamlines  3D streamlines coloured by speed, plus streamlines drawn on
                         the aircraft surface from the wall shear stress (3D view)
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


def pick_preset(lut, names=("Turbo", "Jet", "Cool to Warm")):
    for name in names:
        try:
            if lut.ApplyPreset(name, True):
                return name
        except Exception:
            continue
    return None


def render_streamlines(view, reader, body, latest, bb):
    """Airliner-style picture: 3D streamlines coloured by speed, plus streamlines
    on the aircraft surface following the wall shear stress."""
    bx, by, bz = bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4]
    cx, cy, cz = (bb[0] + bb[1]) / 2, (bb[2] + bb[3]) / 2, (bb[4] + bb[5]) / 2
    size = max(bx, by, bz)
    view.Background = [0.32, 0.33, 0.40]
    view.CameraParallelProjection = 0

    # --- 3D streamlines from a seed grid upstream of the body ----------
    x_seed = bb[0] - 0.25 * size
    seeds = Plane(registrationName="StreamSeeds")
    seeds.Origin = [x_seed, cy - 0.9 * by - 0.1 * size, cz - 0.30 * size]
    seeds.Point1 = [x_seed, cy + 0.9 * by + 0.1 * size, cz - 0.30 * size]
    seeds.Point2 = [x_seed, cy - 0.9 * by - 0.1 * size, cz + 0.30 * size]
    seeds.XResolution = 40
    seeds.YResolution = 14

    domain = reader.GetDataInformation().GetBounds()
    tracer = StreamTracerWithCustomSource(
        registrationName="Streamlines", Input=reader, SeedSource=seeds)
    tracer.Vectors = ["POINTS", "U"]
    tracer.IntegrationDirection = "FORWARD"
    tracer.MaximumStreamlineLength = min(domain[1] - domain[0], 8.0 * size)
    tracer.UpdatePipeline(time=latest)

    tubes = Tube(registrationName="StreamTubes", Input=tracer)
    tubes.Radius = 0.0025 * size
    tubes.UpdatePipeline(time=latest)
    tube_display = Show(tubes, view)
    ColorBy(tube_display, ("POINTS", "U", "Magnitude"))
    lut = GetColorTransferFunction("U")
    pick_preset(lut)
    tube_display.RescaleTransferFunctionToDataRange(True, False)
    tube_display.SetScalarBarVisibility(view, True)
    bar = GetScalarBar(lut, view)
    bar.Title = "Velocity magnitude [m/s]"
    bar.ComponentTitle = ""

    # --- Aircraft surface ----------------------------------------------
    body_display = Show(body, view)
    body_display.Representation = "Surface"
    ColorBy(body_display, None)
    body_display.AmbientColor = [0.10, 0.18, 0.55]
    body_display.DiffuseColor = [0.10, 0.18, 0.55]

    # --- Surface streamlines from the wall shear stress ----------------
    try:
        names = list(body.PointData.keys())
    except Exception:
        names = []
    if "wallShearStress" in names:
        try:
            mask = MaskPoints(registrationName="SurfaceSeeds", Input=body)
            mask.OnRatio = 1
            mask.MaximumNumberofPoints = 4000
            mask.RandomSampling = 1
            mask.GenerateVertices = 1
            mask.SingleVertexPerCell = 0
            surface = StreamTracerWithCustomSource(
                registrationName="SurfaceStreamlines", Input=body, SeedSource=mask)
            surface.Vectors = ["POINTS", "wallShearStress"]
            surface.IntegrationDirection = "BOTH"
            surface.MaximumStreamlineLength = 3.0 * size
            surface.UpdatePipeline(time=latest)
            s_display = Show(surface, view)
            s_display.LineWidth = 1.5
            s_display.RenderLinesAsTubes = 1
            ColorBy(s_display, ("POINTS", "wallShearStress", "Magnitude"))
            wss_lut = GetColorTransferFunction("wallShearStress")
            pick_preset(wss_lut)
            s_display.RescaleTransferFunctionToDataRange(True, False)
            s_display.SetScalarBarVisibility(view, False)
            log("Surface streamlines added")
        except Exception as error:  # noqa: BLE001
            log(f"Surface streamlines skipped: {error}")
    else:
        log("No wallShearStress field found; run the solver step again to write it. "
            "Showing the 3D streamlines only.")

    # --- Camera: raised, front-left three-quarter view -----------------
    Render(view)
    d = 2.6 * size
    fx, fy, fz = cx + 0.9 * bx, cy, cz
    view.CameraFocalPoint = [fx, fy, fz]
    view.CameraPosition = [fx - 0.9 * d, fy - 1.1 * d, fz + 0.9 * d]
    view.CameraViewUp = [0, 0, 1]
    Render(view)
    out = os.path.join(OUTPUT_DIR, f"{CASE_NAME()}_streamlines.png")
    SaveScreenshot(out, view, ImageResolution=[IMAGE_WIDTH, IMAGE_HEIGHT])
    log(f"Screenshot saved: {out}")
    log("=== SUCCESS ===")


def main():
    log("=== ParaView CFD visualization ===")

    if not os.path.exists(CASE_FILE):
        raise FileNotFoundError(f"OpenFOAM case not found: {CASE_FILE}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    axis = SLICE_AXIS if SLICE_AXIS in ("x", "y", "z") else "z"
    if axis != SLICE_AXIS:
        log(f"Unknown SLICE_AXIS '{SLICE_AXIS}', using z")
    field = FIELD if FIELD in ("U", "p", "psurf", "streamlines") else "U"
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
            try:
                body.UpdatePipelineInformation()
                available = list(body.CellArrays.Available)
            except Exception:
                available = []
            wanted = [a for a in ("p", "wallShearStress") if a in available] or ["p"]
            body.CellArrays = wanted
            body.UpdatePipeline(time=latest)
            log(f"Aircraft surface region: {region}")
        else:
            log("Aircraft surface region not found; showing the volume only")
    except Exception as error:  # noqa: BLE001
        body = None
        log(f"Could not load aircraft surface: {error}")

    if field in ("psurf", "streamlines") and body is None:
        raise RuntimeError(f"{field} needs the aircraft surface, which could not be loaded")

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

        Render(view)
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

    # ---- Streamlines view (3D streamlines + surface streamlines) -----
    if field == "streamlines":
        render_streamlines(view, reader, body, latest, bb)
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
    # paraview.simple resets the camera on the first Render(). Do that now, so the
    # framing below is not overwritten by the later screenshot render.
    Render(view)
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

    Render(view)
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
