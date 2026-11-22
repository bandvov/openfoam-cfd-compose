# OpenFOAM CFD with Python + Docker Compose

A small, reproducible external-flow CFD starter. Python creates the OpenFOAM case,
meshes an STL with `blockMesh` + `snappyHexMesh`, checks the mesh, and runs
steady incompressible RANS with `simpleFoam` and `kOmegaSST`.

## Run

1. Put a triangulated, closed STL at `geometry/model.stl`.
2. Copy `.env.example` to `.env` and adjust the operating point/reference dimensions.
3. Start:

   ```bash
   docker compose up --build
   ```

If no STL exists, the script creates a simple rectangular-wing test body. This is
only a pipeline smoke test, not a realistic aircraft model.

Results are written to `results/<CASE_NAME>/`. Open `results/<CASE_NAME>/case.foam`
in ParaView to inspect fields. Force coefficient history is under
`postProcessing/forceCoeffs/`.

## Important assumptions

- STL dimensions are in metres.
- X is the flow direction, Y is spanwise, Z is vertical.
- The STL is approximately aligned with those axes.
- `CHORD` and `WING_AREA` are reference dimensions used for coefficient
  normalization; they do not change the geometry.
- `SPEED` is the free-stream speed in m/s.
- `KINEMATIC_VISCOSITY` is nu in m^2/s (air near sea level: approximately 1.5e-5).
- The initial setup is incompressible. Keep Mach number below about 0.3.
- The default background mesh and surface refinement are deliberately modest.
  Increase refinement and add boundary layers before trusting engineering results.

## Example: 30 m/s aircraft

```env
SPEED=30
AIR_DENSITY=1.225
KINEMATIC_VISCOSITY=1.5e-5
CHORD=1.2
WING_AREA=1.8
MAX_ITER=1500
```

## Re-run

The case directory is recreated each run. Copy any result you want to keep
before starting another run. Change `CASE_NAME` to keep separate named runs.

## Limitations / next steps

This starter is not a validated aircraft-design workflow. Mesh independence,
y+ and boundary-layer resolution, turbulence-model sensitivity, domain-size
sensitivity, and convergence of force coefficients must be checked. For
transonic/compressible flow use a compressible solver and appropriate physics.
The current force directions assume +X drag and +Z lift.
