# Sanctuary roof and doorway audit

All **57 buildings** passed the windowed Godot tour. The audit checked **5,672 roof
cells** and **3,603 visible masonry cells**, using the production town renderer.
Each building was captured from outside, entered through its marked doorway with
a live roof observer, and exited again. Every roof hid on entry and returned on exit.
The renderer also passed the existing column/wall and actor depth regressions.

Roofs now use the wall atlas's shared **(-8, -24)** world-unit projection. Ground
ownership stays unshifted, so the roof's visual offset cannot move its entry trigger.
Doorway repairs removed 25 obstructing wall cells and restored four cells on
disused shore-facing doors. The northwest castle (`house_001`) and southwest
building (`house_041`) now have usable east-side approaches on dry land.

The sheets place City Map reference crops beside each building's roof-on and
roof-off captures. Cyan boxes identify the existing reconstructed footprints.
The source's labels obscure some walls; these sheets do not claim an exact trace
of every original room. The 57 building IDs, services, and four sealed exits remain.

- [Buildings 1–8](tour-01.jpg)
- [Buildings 9–16](tour-02.jpg)
- [Buildings 17–24](tour-03.jpg)
- [Buildings 25–32](tour-04.jpg)
- [Buildings 33–40](tour-05.jpg)
- [Buildings 41–48](tour-06.jpg)
- [Buildings 49–56](tour-07.jpg)
- [Bank](tour-08.jpg)
- [Machine-readable per-building results](report.json)

Full-size examples: [northwest exterior](house_001-outside.png),
[northwest interior](house_001-inside.png), [Temple roof](temple-outside.png),
[Temple interior](temple-inside.png).

Validation: collision bake and wall generator checks; 236 Rust workspace tests;
clippy (two existing load-test warnings); formatting; windowed preview and full
roof tour. Client GDExtension and server release binaries were rebuilt locally.

Reproduce with `res://scenes/test/sanctuary_roof_audit.tscn` in windowed Godot,
then run `scripts/inspect_sanctuary_roofs.py` with Pillow installed.
