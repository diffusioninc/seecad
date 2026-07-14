// SeeCAD reference fixture: simple two-rail library assembly.
//
// Semantic contract:
//   1. Every dimension is expressed in millimetres.
//   2. positive_volume() constructs the custom bridge plate material.
//   3. negative_space() collects all named bridge-plate clearances.
//   4. One plate-level difference() applies the consolidated negative pass.
//   5. Extrusions and hardware are pinned NopSCADlib parts.

include <NopSCADlib/core.scad>
include <NopSCADlib/vitamins/extrusions.scad>
include <NopSCADlib/vitamins/screws.scad>

unit_system = "millimetres";
part = is_undef(part) ? "assembly" : part;
separation = is_undef(separation) ? 0 : separation;

// Assembly envelope and custom part.
rail_type = E2020;
rail_length = 100;
rail_spacing = 50;
rail_size = 20;
plate_size = [80, 70, 4];
plate_corner_radius = 4;
plate_z = rail_size;

// One clamping stack near each plate corner, aligned to the rail slots.
fastener_x_pitch = 60;
fastener_y_pitch = rail_spacing;
fastener_type = M4_cap_screw;
fastener_length = 12;
rail_nut_type = M4_sliding_t_nut;
clearance_overshoot = 2;

assert(unit_system == "millimetres", "SeeCAD designs must declare millimetres explicitly");
assert(
    part == "assembly" || part == "plate" || part == "print_layout",
    "part must be assembly, plate, or print_layout"
);
assert(separation >= 0, "separation must be a non-negative millimetre value");
assert(plate_size.z > 0, "bridge plate must have positive thickness");
assert(rail_spacing > rail_size, "rails must remain separate physical components");
assert(
    fastener_y_pitch == rail_spacing,
    "fastener axes must align with the upper extrusion slots"
);
assert(
    fastener_x_pitch < plate_size.x,
    "fasteners must remain inside the bridge plate X envelope"
);

echo("SEECAD_UNITS", unit_system);
echo("SEECAD_FIXTURE", "simple_library_assembly_v1");
echo("SEECAD_PART", part);

module at_fastener_positions() {
    for (x = [-fastener_x_pitch / 2, fastener_x_pitch / 2],
         y = [-fastener_y_pitch / 2, fastener_y_pitch / 2])
        translate([x, y, 0])
            children();
}

// --- Custom part: positive material ------------------------------------------

module rounded_bridge_plate_material() {
    rounded_rectangle(
        plate_size,
        plate_corner_radius,
        center = false,
        xy_center = true
    );
}

module positive_volume() {
    rounded_bridge_plate_material();
}

// --- Custom part: consolidated named negative space -------------------------

module four_m4_plate_clearance_holes() {
    at_fastener_positions()
        translate([0, 0, -clearance_overshoot])
            poly_cylinder(
                r = screw_clearance_radius(fastener_type),
                h = plate_size.z + 2 * clearance_overshoot,
                center = false
            );
}

module negative_space() {
    four_m4_plate_clearance_holes();
}

module bridge_plate() {
    difference() {
        positive_volume();
        negative_space();
    }
}

// --- Pinned NopSCADlib assembly components ----------------------------------

module extrusion_rails() {
    for (y = [-rail_spacing / 2, rail_spacing / 2])
        translate([0, y, rail_size / 2])
            rotate([0, 90, 0])
                extrusion(rail_type, rail_length, center = true);
}

module rail_t_nuts() {
    // The NopSCADlib T-nut datum is placed at the nominal upper slot opening.
    // This is a visual/bounded placement, not proof of physical engagement.
    at_fastener_positions()
        translate([0, 0, rail_size])
            sliding_t_nut(rail_nut_type);
}

module plate_fasteners(lift = 0) {
    at_fastener_positions()
        translate([0, 0, plate_z + plate_size.z + lift])
            screw_and_washer(fastener_type, fastener_length);
}

module fitted_or_exploded_assembly() {
    extrusion_rails();
    rail_t_nuts();

    color("DodgerBlue")
        translate([0, 0, plate_z + separation])
            bridge_plate();

    plate_fasteners(2 * separation);
}

if (part == "assembly")
    fitted_or_exploded_assembly();
else if (part == "plate" || part == "print_layout")
    bridge_plate();
