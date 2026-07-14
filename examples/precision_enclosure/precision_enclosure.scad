// SeeCAD reference fixture: precision electronics inspection enclosure.
//
// Semantic contract:
//   1. All dimensions are millimetres.
//   2. positive_volume() constructs every material feature.
//   3. negative_space() consolidates every hole, clearance, and passage.
//   4. The final model contains exactly one design-level difference().
//
// NopSCADlib supplies rounded printable geometry, polyholes, support-free
// horizontal passages, and the pinned F1BM3 heat-set insert profile.

include <NopSCADlib/core.scad>
include <NopSCADlib/vitamins/inserts.scad>

unit_system = "millimetres";
part = is_undef(part) ? "base" : part;
explode = is_undef(explode) ? 0 : explode;

// Overall enclosure envelope.
outer_size = [86, 62, 24];
outer_corner_radius = 8;
base_floor_thickness = 3;
wall_thickness = 3;
lid_thickness = 3;

// Removable lid locating geometry.
lid_skirt_thickness = 1.6;
lid_skirt_depth = 2;
lid_fit_clearance = 0.35;

// Nominal 54 x 32 mm sensor/controller board and its M2 pilot pattern.
pcb_size = [54, 32, 1.6];
pcb_hole_pitch = [48, 26];
pcb_standoff_radius = 3.5;
pcb_standoff_height = 5;
pcb_pilot_radius = 1.15;
pcb_pilot_depth = 4.5;

// Lid fasteners use the actual NopSCADlib F1BM3 insertion-hole profile.
lid_insert = F1BM3;
lid_boss_centres = [
    [ outer_size.x / 2 - outer_corner_radius,  outer_size.y / 2 - outer_corner_radius],
    [-outer_size.x / 2 + outer_corner_radius,  outer_size.y / 2 - outer_corner_radius],
    [ outer_size.x / 2 - outer_corner_radius, -outer_size.y / 2 + outer_corner_radius],
    [-outer_size.x / 2 + outer_corner_radius, -outer_size.y / 2 + outer_corner_radius],
];

// Tool passages deliberately extend well past both faces of their walls. This
// keeps later dimensional adjustments local to one named subtraction instead
// of rebuilding a chain of alternating booleans.
passage_overshoot = 4;

assert(unit_system == "millimetres", "SeeCAD designs must declare millimetres explicitly");
assert(
    part == "base" || part == "lid" || part == "assembly" || part == "print_layout",
    "part must be base, lid, assembly, or print_layout"
);
assert(base_floor_thickness >= 2.4, "base floor is below the bounded FDM minimum");
assert(wall_thickness >= 2.4, "wall is below the bounded FDM minimum");
assert(pcb_size.x + 2 < outer_size.x - 2 * wall_thickness, "PCB lacks X clearance");
assert(pcb_size.y + 2 < outer_size.y - 2 * wall_thickness, "PCB lacks Y clearance");
assert(
    pcb_standoff_height > pcb_pilot_depth,
    "blind PCB pilot holes must stop above the enclosure floor"
);

echo("SEECAD_UNITS", unit_system);
echo("SEECAD_FIXTURE", "precision_enclosure_v1");
echo("SEECAD_PART", part);

module at_xy_positions(positions) {
    for (position = positions)
        translate([position.x, position.y, 0])
            children();
}

module pcb_hole_positions() {
    for (x = [-pcb_hole_pitch.x / 2, pcb_hole_pitch.x / 2],
         y = [-pcb_hole_pitch.y / 2, pcb_hole_pitch.y / 2])
        translate([x, y, 0])
            children();
}

// --- Positive semantic features ------------------------------------------------

module enclosure_floor() {
    rounded_rectangle(
        [outer_size.x, outer_size.y, base_floor_thickness],
        outer_corner_radius,
        center = false,
        xy_center = true
    );
}

module perimeter_walls() {
    // The eps overlap removes coplanar internal seams where walls meet the floor.
    wall_z0 = base_floor_thickness - eps;
    wall_height = outer_size.z - wall_z0;
    surface_inset = eps;
    corner_span_x = outer_size.x - 2 * outer_corner_radius;
    corner_span_y = outer_size.y - 2 * outer_corner_radius;

    translate([0, 0, wall_z0]) {
        // Straight wall runs terminate at the tangent points of the corner posts.
        for (y = [-1, 1])
            translate([
                0,
                y * (outer_size.y / 2 - surface_inset - wall_thickness / 2),
                wall_height / 2
            ])
                cube([corner_span_x, wall_thickness, wall_height], center = true);

        for (x = [-1, 1])
            translate([
                x * (outer_size.x / 2 - surface_inset - wall_thickness / 2),
                0,
                wall_height / 2
            ])
                cube([wall_thickness, corner_span_y, wall_height], center = true);

        // Full-height corner posts form both the rounded exterior and insert bosses.
        // The imperceptible surface inset prevents coincident mesh faces at z=3.
        at_xy_positions(lid_boss_centres)
            cylinder(r = outer_corner_radius - surface_inset, h = wall_height);
    }
}

module pcb_supports() {
    // Four isolated positive standoffs keep the board above the enclosure floor.
    pcb_hole_positions()
        translate([0, 0, base_floor_thickness - eps])
            cylinder(r = pcb_standoff_radius, h = pcb_standoff_height + eps);

    // Two low datum rails establish the board's Y location without trapping it.
    rail_length = pcb_size.x - 12;
    rail_width = 1.4;
    rail_height = 1.2;
    for (y = [-1, 1])
        translate([
            0,
            y * (pcb_size.y / 2 + lid_fit_clearance + rail_width / 2),
            base_floor_thickness + (rail_height - eps) / 2
        ])
            cube([rail_length, rail_width, rail_height + eps], center = true);
}

module base_positive_volume() {
    union() {
        enclosure_floor();
        perimeter_walls();
        pcb_supports();
    }
}

module lid_skirt() {
    // The skirt is split into four short rails so it clears the base's rounded
    // corner insert posts while still locating the lid in X and Y.
    z0 = outer_size.z - lid_skirt_depth;
    front_back_length = outer_size.x - 4 * outer_corner_radius;
    left_right_length = outer_size.y - 4 * outer_corner_radius;
    skirt_x = outer_size.x / 2 - wall_thickness - lid_fit_clearance - lid_skirt_thickness / 2;
    skirt_y = outer_size.y / 2 - wall_thickness - lid_fit_clearance - lid_skirt_thickness / 2;

    for (y = [-1, 1])
        translate([0, y * skirt_y, z0 + lid_skirt_depth / 2])
            cube([front_back_length, lid_skirt_thickness, lid_skirt_depth], center = true);

    for (x = [-1, 1])
        translate([x * skirt_x, 0, z0 + lid_skirt_depth / 2])
            cube([lid_skirt_thickness, left_right_length, lid_skirt_depth], center = true);
}

module lid_positive_volume() {
    union() {
        translate([0, 0, outer_size.z])
            rounded_rectangle(
                [outer_size.x, outer_size.y, lid_thickness],
                outer_corner_radius,
                center = false,
                xy_center = true
            );
        lid_skirt();
    }
}

// --- Consolidated negative semantic features ----------------------------------

module lid_insert_holes() {
    // Blind F1BM3 heat-set insert holes open from the top of each corner post.
    at_xy_positions(lid_boss_centres)
        translate([0, 0, outer_size.z])
            insert_hole(lid_insert);
}

module pcb_mounting_pilot_holes() {
    // Named blind M2 pilot holes stop 0.5 mm above the enclosure floor.
    pilot_z = base_floor_thickness + pcb_standoff_height - pcb_pilot_depth;
    pcb_hole_positions()
        translate([0, 0, pilot_z])
            poly_cylinder(r = pcb_pilot_radius, h = pcb_pilot_depth + eps);
}

module usb_c_tool_access_channel() {
    // 15 x 7 mm support-free service passage through the front wall.
    channel_length = wall_thickness + 2 * passage_overshoot;
    translate([0, -(outer_size.y - wall_thickness) / 2, 11])
        rotate([90, 0, 0])
            tearslot(h = channel_length, r = 3.5, w = 8, center = true, plus = true);
}

module probe_tool_access_channel() {
    // A long 5 mm probe/screwdriver passage reaches the PCB test-point zone.
    channel_length = wall_thickness + 2 * passage_overshoot;
    translate([(outer_size.x - wall_thickness) / 2, 5, 13])
        rotate([90, 0, 90])
            teardrop_plus(h = channel_length, r = 2.5, center = true);
}

module calibration_tool_access_channel() {
    // Rear support-free passage accepts a 3 mm calibration key without lid removal.
    channel_length = wall_thickness + 2 * passage_overshoot;
    translate([-18, (outer_size.y - wall_thickness) / 2, 14])
        rotate([90, 0, 0])
            teardrop_plus(h = channel_length, r = 1.7, center = true);
}

module tool_access_channels() {
    usb_c_tool_access_channel();
    probe_tool_access_channel();
    calibration_tool_access_channel();
}

module base_negative_space() {
    union() {
        lid_insert_holes();
        pcb_mounting_pilot_holes();
        tool_access_channels();
    }
}

module lid_fastener_clearance_holes() {
    // M3 free-fit holes align exactly with the base's named insert holes.
    at_xy_positions(lid_boss_centres)
        translate([0, 0, outer_size.z - 1])
            poly_cylinder(r = 1.7, h = lid_thickness + 2);
}

module sensor_airflow_channels() {
    // Three bounded ventilation slots expose the sensor while rejecting fingers.
    for (y = [-6, 0, 6])
        translate([6, y, outer_size.z - 1])
            slot(r = 1.25, l = 18, h = lid_thickness + 2, center = false);
}

module status_light_pipe_clearance() {
    translate([-22, 0, outer_size.z - 1])
        poly_cylinder(r = 2.1, h = lid_thickness + 2);
}

module lid_negative_space() {
    union() {
        lid_fastener_clearance_holes();
        sensor_airflow_channels();
        status_light_pipe_clearance();
    }
}

// --- Part transforms and the sole design-level boolean ------------------------

module lid_print_transform() {
    // Flip the assembled lid so its broad face prints on the bed without support.
    translate([0, 0, outer_size.z + lid_thickness])
        rotate([180, 0, 0])
            children();
}

module positive_volume() {
    union() {
        if (part == "base" || part == "assembly" || part == "print_layout")
            base_positive_volume();

        if (part == "lid")
            lid_print_transform()
                lid_positive_volume();

        if (part == "assembly")
            translate([0, 0, explode])
                lid_positive_volume();

        if (part == "print_layout")
            translate([outer_size.x + 12, 0, 0])
                lid_print_transform()
                    lid_positive_volume();
    }
}

module negative_space() {
    union() {
        if (part == "base" || part == "assembly" || part == "print_layout")
            base_negative_space();

        if (part == "lid")
            lid_print_transform()
                lid_negative_space();

        if (part == "assembly")
            translate([0, 0, explode])
                lid_negative_space();

        if (part == "print_layout")
            translate([outer_size.x + 12, 0, 0])
                lid_print_transform()
                    lid_negative_space();
    }
}

difference() {
    positive_volume();
    negative_space();
}
