from math import atan2, degrees, exp
from random import Random, uniform

from PIL import Image, ImageFilter
from panda3d.bullet import (
    BulletVehicle,
)
from panda3d.core import Point3 as PandaPoint3, Vec3 as PandaVec3
from ursina import *
from ursina import application
from ursina.color import black, rgb32, rgba32, white

app = Ursina()
window.title = 'Terepjáró - domborzati pálya'
window.fps_counter.enabled = True
window.color = rgb32(135, 180, 215)

MAP_IMAGE = Path(__file__).with_name('COL-CLASSIC.png')
MAP_RESOLUTION = 128
WORLD_SIZE = 300
WORLD_HALF = WORLD_SIZE / 2
TILE_SEAM_BLEND_WIDTH = 8
SUBPIXEL_DIVISIONS = 2
SUBPIXEL_COLOR_VARIATION = 5
MAX_MOUNTAIN_HEIGHT = 7
HEIGHT_SMOOTHING_RADIUS = 1

MAX_FORWARD_SPEED_KMH = 200
MAX_REVERSE_SPEED_KMH = 200
ENGINE_FORCE = 2200
REVERSE_FORCE = 1000
BRAKE_FORCE = 20
PARKING_BRAKE_FORCE = 1000
STEERING_ANGLE = 15
REVERSE_STEERING_SCALE = 15
STEERING_ASSIST_TORQUE = 1800
FLIGHT_ACCELERATION = 16
FLIGHT_TORQUE = PandaVec3(3000, 2600, 3400)
CAMERA_DISTANCE = 15
CAMERA_HEIGHT = 8
CAMERA_FOLLOW_SPEED = 2
CAMERA_TURN_FOLLOW_SPEED = 3
CRASH_SPEED_THRESHOLD = 32
DAMAGE_ARM_DELAY = 2.0
WHEEL_IMPACT_DISTANCE_THRESHOLD = 0.06
WHEEL_IMPACT_SPEED_THRESHOLD = 2.0
WHEEL_DENT_SEVERITY_THRESHOLD = 0.20
SUSPENSION_COLLAPSE_SEVERITY_THRESHOLD = 0.97
SUSPENSION_VISUAL_SMOOTHING = 24
DUST_PARTICLE_COUNT = 96


def pixel_height(pixel):
    r, g, b = pixel
    brightness = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    darkness = 1 - brightness

    if b > r * 1.3 and b > g * 1.15:
        return -1.4

    is_brown = r > g + 8 and g > b + 8 and b > 15 and r < 215
    if is_brown:
        return 0.4 + darkness ** 1.4 * MAX_MOUNTAIN_HEIGHT

    is_green = g > r + 8 and g > b + 6
    if is_green:
        return darkness ** 1.8 * 2.5

    return darkness ** 1.8 * 1.8


with Image.open(MAP_IMAGE) as source:
    map_image = source.convert('RGB').resize(
        (MAP_RESOLUTION, MAP_RESOLUTION),
        Image.Resampling.NEAREST,
    )

raw_heightmap = [
    [
        pixel_height(map_image.getpixel((column, row)))
        for column in range(MAP_RESOLUTION)
    ]
    for row in range(MAP_RESOLUTION)
]
minimum_height = min(min(row) for row in raw_heightmap)
maximum_height = max(max(row) for row in raw_heightmap)
height_image = Image.new('L', (MAP_RESOLUTION, MAP_RESOLUTION))
height_image.putdata(
    [
        round((height - minimum_height) / (maximum_height - minimum_height) * 255)
        for row in raw_heightmap
        for height in row
    ]
)
smoothed_height_image = height_image.filter(
    ImageFilter.GaussianBlur(radius=HEIGHT_SMOOTHING_RADIUS)
)
smoothed_values = list(smoothed_height_image.tobytes())
heightmap = [
    [
        minimum_height
        + smoothed_values[row * MAP_RESOLUTION + column] / 255
        * (maximum_height - minimum_height)
        for column in range(MAP_RESOLUTION)
    ]
    for row in range(MAP_RESOLUTION)
]

seam_width = min(TILE_SEAM_BLEND_WIDTH, MAP_RESOLUTION // 4)
for row in heightmap:
    left_edge = row[0]
    right_edge = row[-1]
    seam_height = (left_edge + right_edge) / 2
    for offset in range(seam_width + 1):
        blend = 1 - (offset / seam_width) ** 2 * (
                3 - 2 * offset / seam_width
        )
        row[offset] += (seam_height - left_edge) * blend
        row[-1 - offset] += (seam_height - right_edge) * blend

for column in range(MAP_RESOLUTION):
    top_edge = heightmap[0][column]
    bottom_edge = heightmap[-1][column]
    seam_height = (top_edge + bottom_edge) / 2
    for offset in range(seam_width + 1):
        blend = 1 - (offset / seam_width) ** 2 * (
                3 - 2 * offset / seam_width
        )
        heightmap[offset][column] += (seam_height - top_edge) * blend
        heightmap[-1 - offset][column] += (seam_height - bottom_edge) * blend

terrain_vertices = []
terrain_triangles = []
for row in range(MAP_RESOLUTION):
    world_z = (0.5 - row / (MAP_RESOLUTION - 1)) * WORLD_SIZE
    for column in range(MAP_RESOLUTION):
        world_x = (column / (MAP_RESOLUTION - 1) - 0.5) * WORLD_SIZE
        terrain_vertices.append(Vec3(world_x, heightmap[row][column], world_z))

for row in range(MAP_RESOLUTION - 1):
    for column in range(MAP_RESOLUTION - 1):
        top_left = row * MAP_RESOLUTION + column
        top_right = top_left + 1
        bottom_left = top_left + MAP_RESOLUTION
        bottom_right = bottom_left + 1
        terrain_triangles.extend(
            (top_left, bottom_left, top_right, top_right, bottom_left, bottom_right)
        )

terrain_mesh = Mesh(
    vertices=terrain_vertices,
    triangles=terrain_triangles,
)
terrain_mesh.generate_normals(smooth=False)


def interpolated_cell_value(values, row, column, u, v):
    top_left = values[row][column]
    top_right = values[row][column + 1]
    bottom_left = values[row + 1][column]
    bottom_right = values[row + 1][column + 1]
    if u + v <= 1:
        return top_left * (1 - u - v) + top_right * u + bottom_left * v
    return (
            top_right * (1 - v)
            + bottom_left * (1 - u)
            + bottom_right * (u + v - 1)
    )


source_normals = [
    [Vec3(*terrain_mesh.normals[row * MAP_RESOLUTION + column]) for column in range(MAP_RESOLUTION)]
    for row in range(MAP_RESOLUTION)
]
pixel_vertices = []
pixel_normals = []
pixel_colors = []
pixel_triangles = []
subpixel_random = Random(2026)
for row in range(MAP_RESOLUTION - 1):
    for column in range(MAP_RESOLUTION - 1):
        red, green, blue = map_image.getpixel((column, row))
        cell_samples = []
        for sample_row in range(SUBPIXEL_DIVISIONS + 1):
            v = sample_row / SUBPIXEL_DIVISIONS
            samples = []
            for sample_column in range(SUBPIXEL_DIVISIONS + 1):
                u = sample_column / SUBPIXEL_DIVISIONS
                grid_row = row + v
                grid_column = column + u
                world_x = (grid_column / (MAP_RESOLUTION - 1) - 0.5) * WORLD_SIZE
                world_z = (0.5 - grid_row / (MAP_RESOLUTION - 1)) * WORLD_SIZE
                height = interpolated_cell_value(heightmap, row, column, u, v)
                normal = interpolated_cell_value(
                    source_normals,
                    row,
                    column,
                    u,
                    v,
                ).normalized()
                samples.append((Vec3(world_x, height, world_z), normal))
            cell_samples.append(samples)

        for subpixel_row in range(SUBPIXEL_DIVISIONS):
            for subpixel_column in range(SUBPIXEL_DIVISIONS):
                pixel_index = len(pixel_vertices)
                corners = (
                    (subpixel_row, subpixel_column),
                    (subpixel_row, subpixel_column + 1),
                    (subpixel_row + 1, subpixel_column),
                    (subpixel_row + 1, subpixel_column + 1),
                )
                for sample_row, sample_column in corners:
                    vertex, normal = cell_samples[sample_row][sample_column]
                    pixel_vertices.append(vertex)
                    pixel_normals.append(normal)

                tone_shift = subpixel_random.randint(
                    -SUBPIXEL_COLOR_VARIATION,
                    SUBPIXEL_COLOR_VARIATION,
                )
                pixel_color = rgb32(
                    max(0, min(255, red + tone_shift + subpixel_random.randint(-3, 3))),
                    max(0, min(255, green + tone_shift + subpixel_random.randint(-3, 3))),
                    max(0, min(255, blue + tone_shift + subpixel_random.randint(-3, 3))),
                )
                pixel_colors.extend((pixel_color,) * 4)
                pixel_triangles.extend(
                    (
                        pixel_index,
                        pixel_index + 2,
                        pixel_index + 1,
                        pixel_index + 1,
                        pixel_index + 2,
                        pixel_index + 3,
                    )
                )

pixelated_terrain_mesh = Mesh(
    vertices=pixel_vertices,
    triangles=pixel_triangles,
    colors=pixel_colors,
    normals=pixel_normals,
)
terrain_visuals = []
for tile_x in (-1, 0, 1):
    for tile_z in (-1, 0, 1):
        tile_mesh = pixelated_terrain_mesh.copyTo(scene)
        terrain_visuals.append(
            Entity(
                model=tile_mesh,
                position=(tile_x * WORLD_SIZE, 0, tile_z * WORLD_SIZE),
                color=white,
            )
        )

AmbientLight(color=rgb32(125, 125, 125))
sun = DirectionalLight(color=rgb32(210, 205, 190))
sun.look_at(Vec3(-1, -2, 1))
Sky()


def terrain_height(x, z):
    column = min(max((x / WORLD_SIZE + 0.5) * (MAP_RESOLUTION - 1), 0), MAP_RESOLUTION - 1)
    row = min(max((0.5 - z / WORLD_SIZE) * (MAP_RESOLUTION - 1), 0), MAP_RESOLUTION - 1)
    left = min(int(column), MAP_RESOLUTION - 2)
    top = min(int(row), MAP_RESOLUTION - 2)
    x_fraction = column - left
    z_fraction = row - top

    top_height = heightmap[top][left] * (1 - x_fraction) + heightmap[top][left + 1] * x_fraction
    bottom_height = (
            heightmap[top + 1][left] * (1 - x_fraction)
            + heightmap[top + 1][left + 1] * x_fraction
    )
    return top_height * (1 - z_fraction) + bottom_height * z_fraction


def terrain_surface_height(x, z):
    local_x = (x + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
    local_z = (z + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
    column = (local_x / WORLD_SIZE + 0.5) * (MAP_RESOLUTION - 1)
    row = (0.5 - local_z / WORLD_SIZE) * (MAP_RESOLUTION - 1)
    left = min(int(column), MAP_RESOLUTION - 2)
    top = min(int(row), MAP_RESOLUTION - 2)
    x_fraction = column - left
    z_fraction = row - top

    return interpolated_cell_value(
        heightmap,
        top,
        left,
        x_fraction,
        z_fraction,
    )


def smooth_angle(current, target, amount):
    difference = (target - current + 180) % 360 - 180
    return current + difference * amount


physics_world = BulletWorld()
physics_world.setGravity(PandaVec3(0, -9.81, 0))

bullet_terrain_mesh = BulletTriangleMesh()
for index in range(0, len(terrain_triangles), 3):
    a = terrain_vertices[terrain_triangles[index]]
    b = terrain_vertices[terrain_triangles[index + 1]]
    c = terrain_vertices[terrain_triangles[index + 2]]
    bullet_terrain_mesh.addTriangle(
        PandaVec3(a.x, a.y, a.z),
        PandaVec3(c.x, c.y, c.z),
        PandaVec3(b.x, b.y, b.z),
        False,
    )

terrain_shape = BulletTriangleMeshShape(bullet_terrain_mesh, False)
terrain_bodies = []
terrain_nodes = []
for tile_x in (-1, 0, 1):
    for tile_z in (-1, 0, 1):
        terrain_body = BulletRigidBodyNode(f'terrain-{tile_x}-{tile_z}')
        terrain_body.addShape(terrain_shape)
        terrain_body.setFriction(1.0)
        terrain_node = render.attachNewNode(terrain_body)
        terrain_node.setPos(tile_x * WORLD_SIZE, 0, tile_z * WORLD_SIZE)
        physics_world.attachRigidBody(terrain_body)
        terrain_bodies.append(terrain_body)
        terrain_nodes.append(terrain_node)

chassis_body = BulletRigidBodyNode('blue-offroad-chassis')
chassis_body.setMass(850)
chassis_body.setDeactivationEnabled(False)
chassis_body.setLinearDamping(0.025)
chassis_body.setAngularDamping(0.75)
chassis_body.setCcdMotionThreshold(1.0)
chassis_body.setCcdSweptSphereRadius(0.35)
chassis_body.addShape(
    BulletBoxShape(PandaVec3(0.85, 0.38, 1.3)),
    TransformState.makePos(PandaVec3(0, -0.08, 0)),
)
chassis_body.setFriction(0.8)
chassis_body.setRestitution(0.05)

initial_car_position = Vec3(0, terrain_height(0, 0) + 2, 0)
initial_camera_position = Vec3(
    0,
    terrain_height(0, 0) + CAMERA_HEIGHT,
    -CAMERA_DISTANCE,
)
chassis_node = render.attachNewNode(chassis_body)
chassis_node.setPos(initial_car_position.x, initial_car_position.y, initial_car_position.z)
physics_world.attachRigidBody(chassis_body)

vehicle = BulletVehicle(physics_world, chassis_body)
vehicle.setCoordinateSystem(1)

car_visual = Entity(parent=chassis_node)
SHADOW_COLUMNS = 13
SHADOW_ROWS = 17
SHADOW_WIDTH = 2.2
SHADOW_LENGTH = 3
shadow_vertices = []
shadow_triangles = []
for row in range(SHADOW_ROWS):
    local_z = SHADOW_LENGTH / 2 - row * SHADOW_LENGTH / (SHADOW_ROWS - 1)
    for column in range(SHADOW_COLUMNS):
        local_x = -SHADOW_WIDTH / 2 + column * SHADOW_WIDTH / (SHADOW_COLUMNS - 1)
        world_x = initial_car_position.x + local_x
        world_z = initial_car_position.z + local_z
        shadow_vertices.append(
            Vec3(world_x, terrain_surface_height(world_x, world_z) + 0.04, world_z)
        )
for row in range(SHADOW_ROWS - 1):
    for column in range(SHADOW_COLUMNS - 1):
        top_left = row * SHADOW_COLUMNS + column
        top_right = top_left + 1
        bottom_left = top_left + SHADOW_COLUMNS
        bottom_right = bottom_left + 1
        shadow_triangles.extend(
            (top_left, bottom_left, top_right, top_right, bottom_left, bottom_right)
        )
car_shadow_mesh = Mesh(
    vertices=shadow_vertices,
    triangles=shadow_triangles,
    static=False,
)
car_shadow = Entity(
    parent=scene,
    model=car_shadow_mesh,
    color=rgba32(20, 25, 30, 125),
    double_sided=True,
    unlit=True,
)

body_sections = (
    (-1.34, 0.60, 0.54, -0.12, 0.22),
    (-1.16, 0.74, 0.66, -0.18, 0.40),
    (-0.72, 0.80, 0.71, -0.20, 0.42),
    (0.48, 0.80, 0.72, -0.20, 0.38),
    (1.04, 0.72, 0.66, -0.16, 0.31),
    (1.34, 0.60, 0.56, -0.12, 0.25),
)
body_vertices = []
body_triangles = []
for z, bottom_width, top_width, bottom_y, top_y in body_sections:
    bevel = 0.10
    profile = (
        (-bottom_width + bevel, bottom_y),
        (bottom_width - bevel, bottom_y),
        (bottom_width, bottom_y + bevel),
        (top_width, top_y - bevel),
        (top_width - bevel, top_y),
        (-top_width + bevel, top_y),
        (-top_width, top_y - bevel),
        (-bottom_width, bottom_y + bevel),
    )
    body_vertices.extend(Vec3(x, y, z) for x, y in profile)

for section_index in range(len(body_sections) - 1):
    rear_ring = section_index * 8
    front_ring = rear_ring + 8
    for profile_index in range(8):
        next_profile_index = (profile_index + 1) % 8
        rear_current = rear_ring + profile_index
        rear_next = rear_ring + next_profile_index
        front_current = front_ring + profile_index
        front_next = front_ring + next_profile_index
        body_triangles.extend(
            (rear_current, rear_next, front_next, rear_current, front_next, front_current)
        )

rear_z, _, _, rear_bottom, rear_top = body_sections[0]
rear_center = len(body_vertices)
body_vertices.append(Vec3(0, (rear_bottom + rear_top) / 2, rear_z))
front_z, _, _, front_bottom, front_top = body_sections[-1]
front_center = len(body_vertices)
body_vertices.append(Vec3(0, (front_bottom + front_top) / 2, front_z))
front_ring = (len(body_sections) - 1) * 8
for profile_index in range(8):
    next_profile_index = (profile_index + 1) % 8
    body_triangles.extend(
        (
            rear_center,
            next_profile_index,
            profile_index,
            front_center,
            front_ring + profile_index,
            front_ring + next_profile_index,
        )
    )

body_mesh = Mesh(vertices=body_vertices, triangles=body_triangles)
body_mesh.generate_normals(smooth=True)
car_body = Entity(
    parent=car_visual,
    model=body_mesh,
    color=rgb32(25, 105, 235),
    double_sided=True,
)
initial_car_body_color = car_body.color
original_body_vertices = tuple(
    Vec3(vertex.x, vertex.y, vertex.z) for vertex in body_mesh.vertices
)
body_dents = []


def dent_body(local_position, severity):
    outward = Vec3(local_position.x, 0, local_position.z)
    if outward.length() < 0.001:
        outward = Vec3(1, 0, 0)
    else:
        outward = outward.normalized()

    body_dents.append(
        (
            Vec3(local_position.x, local_position.y, local_position.z),
            outward,
            0.06 + 0.22 * severity,
            0.95,
        )
    )
    if len(body_dents) > 12:
        body_dents.pop(0)

    deformed_vertices = []
    for vertex in original_body_vertices:
        offset = Vec3(0, 0, 0)
        for dent_position, dent_direction, depth, radius in body_dents:
            distance = (vertex - dent_position).length()
            falloff = max(0, 1 - distance / radius)
            offset -= dent_direction * depth * falloff ** 2
        if offset.length() > 0.38:
            offset = offset.normalized() * 0.38
        deformed_vertices.append(vertex + offset)

    body_mesh.vertices = deformed_vertices
    body_mesh.generate_normals(smooth=True)


cabin_vertices = (
    Vec3(-0.68, 0.34, 0.68),
    Vec3(0.68, 0.34, 0.68),
    Vec3(0.68, 0.34, -0.98),
    Vec3(-0.68, 0.34, -0.98),
    Vec3(-0.52, 0.91, 0.20),
    Vec3(0.52, 0.91, 0.20),
    Vec3(0.52, 0.91, -0.62),
    Vec3(-0.52, 0.91, -0.62),
)
cabin_faces = (
    (0, 4, 7, 3),
    (1, 2, 6, 5),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (3, 7, 6, 2),
)
cabin_triangles = []
for face in cabin_faces:
    cabin_triangles.extend((face[0], face[1], face[2], face[0], face[2], face[3]))
cabin_mesh = Mesh(vertices=cabin_vertices, triangles=cabin_triangles)
cabin_mesh.generate_normals(smooth=False)
Entity(
    parent=car_visual,
    model=cabin_mesh,
    color=rgb32(35, 122, 225),
    double_sided=True,
)


def create_window(points):
    window_mesh = Mesh(
        vertices=[Vec3(*point) for point in points],
        triangles=(0, 1, 2, 0, 2, 3),
    )
    window_mesh.generate_normals(smooth=False)
    Entity(
        parent=car_visual,
        model=window_mesh,
        color=rgb32(24, 55, 82),
        double_sided=True,
    )


create_window(((-0.55, 0.39, 0.71), (0.55, 0.39, 0.71), (0.44, 0.85, 0.24), (-0.44, 0.85, 0.24)))
create_window(((-0.66, 0.39, 0.50), (-0.51, 0.84, 0.15), (-0.51, 0.84, -0.57), (-0.66, 0.39, -0.87)))
create_window(((0.66, 0.39, 0.50), (0.51, 0.84, 0.15), (0.51, 0.84, -0.57), (0.66, 0.39, -0.87)))
create_window(((-0.55, 0.39, -0.99), (-0.44, 0.85, -0.64), (0.44, 0.85, -0.64), (0.55, 0.39, -0.99)))

Entity(
    parent=car_visual,
    model='sphere',
    scale=(1.05, 0.12, 0.88),
    position=(0, 0.91, -0.20),
    color=rgb32(20, 86, 190),
)
for side in (-1, 1):
    Entity(
        parent=car_visual,
        model='sphere',
        scale=(0.34, 0.18, 0.78),
        position=(side * 0.95, -0.02, 0.95),
        color=rgb32(18, 63, 145),
    )
    Entity(
        parent=car_visual,
        model='sphere',
        scale=(0.34, 0.18, 0.78),
        position=(side * 0.95, -0.02, -0.95),
        color=rgb32(18, 63, 145),
    )
    Entity(
        parent=car_visual,
        model='sphere',
        scale=(0.20, 0.14, 0.15),
        position=(side * 0.72, 0.57, 0.18),
        color=rgb32(25, 72, 135),
    )

for bumper_z in (-1.43, 1.43):
    Entity(
        parent=car_visual,
        model=Cylinder(start=-0.5),
        scale=(0.12, 1.60, 0.12),
        rotation_z=90,
        position=(0, 0.0, bumper_z),
        color=rgb32(145, 155, 165),
    )
Entity(
    parent=car_visual,
    model='cube',
    scale=(0.58, 0.22, 0.06),
    position=(0, 0.08, 1.31),
    color=rgb32(28, 40, 55),
)
for side in (-1, 1):
    Entity(
        parent=car_visual,
        model='sphere',
        scale=(0.18, 0.13, 0.10),
        position=(side * 0.45, 0.18, 1.29),
        color=rgb32(245, 220, 145),
    )
    Entity(
        parent=car_visual,
        model='sphere',
        scale=(0.15, 0.12, 0.09),
        position=(side * 0.48, 0.15, -1.30),
        color=rgb32(210, 55, 45),
    )

for axle_z in (0.95, -0.95):
    Entity(
        parent=car_visual,
        model='sphere',
        scale=(0.38, 0.27, 0.38),
        position=(0, -0.30, axle_z),
        color=rgb32(75, 82, 90),
    )

wheel_visuals = []
vehicle_wheels = []
suspension_visuals = []
for wheel_x, wheel_z, is_front in (
        (-0.95, 0.95, True),
        (0.95, 0.95, True),
        (-0.95, -0.95, False),
        (0.95, -0.95, False),
):
    wheel_visual = Entity(parent=scene)
    wheel_model = Entity(parent=wheel_visual)
    Entity(
        parent=wheel_model,
        model=Cylinder(start=-0.5),
        scale=(0.44, 0.3, 0.44),
        rotation_z=90,
        color=black,
    )
    Entity(
        parent=wheel_model,
        model=Cylinder(start=-0.5),
        scale=(0.31, 0.31, 0.31),
        rotation_z=90,
        color=rgb32(135, 145, 155),
    )
    Entity(
        parent=wheel_model,
        model=Cylinder(start=-0.5),
        scale=(0.19, 0.325, 0.19),
        rotation_z=90,
        color=rgb32(52, 62, 72),
    )
    Entity(
        parent=wheel_model,
        model='sphere',
        scale=(0.12, 0.12, 0.12),
        color=rgb32(185, 190, 195),
    )
    wheel_index = len(vehicle_wheels)
    wheel = vehicle.createWheel()
    wheel.setNode(wheel_visual.node())
    wheel.setChassisConnectionPointCs(PandaVec3(wheel_x, -0.2, wheel_z))
    wheel.setWheelDirectionCs(PandaVec3(0, -1, 0))
    wheel.setWheelAxleCs(PandaVec3(1, 0, 0))
    wheel.setWheelRadius(0.42)
    wheel.setMaxSuspensionTravelCm(45)
    wheel.setSuspensionStiffness(38)
    wheel.setWheelsDampingRelaxation(2.7)
    wheel.setWheelsDampingCompression(5)
    wheel.setFrictionSlip(6)
    wheel.setRollInfluence(0.04)
    wheel.setFrontWheel(is_front)
    original_suspension_stiffness = wheel.getSuspensionStiffness()
    original_max_suspension_force = wheel.getMaxSuspensionForce()
    original_compression_damping = wheel.getWheelsDampingCompression()
    wheel_visuals.append(wheel_visual)
    vehicle_wheels.append(wheel)
    suspension_visuals.append(
        {
            'wheel_visual': wheel_visual,
            'wheel_model': wheel_model,
            'wheel_index': wheel_index,
            'wheel_x': wheel_x,
            'wheel_z': wheel_z,
            'original_suspension_stiffness': original_suspension_stiffness,
            'original_max_suspension_force': original_max_suspension_force,
            'original_compression_damping': original_compression_damping,
            'previous_suspension_length': None,
            'impact_cooldown': 0.0,
            'impact_visual': 0.0,
            'compression': 0.0,
            'smoothed_wheel_local_position': None,
            'collapsed': False,
            'particle_timer': 0.0,
            'shock': Entity(
                parent=scene,
                model=Cylinder(start=-0.5),
                scale=(0.09, 1, 0.09),
                color=rgb32(75, 85, 95),
            ),
            'piston': Entity(
                parent=scene,
                model=Cylinder(start=-0.5),
                scale=(0.04, 1, 0.04),
                color=rgb32(185, 190, 195),
            ),
            'front_arm': Entity(
                parent=scene,
                model=Cylinder(start=-0.5),
                scale=(0.06, 1, 0.06),
                color=rgb32(55, 65, 75),
            ),
            'rear_arm': Entity(
                parent=scene,
                model=Cylinder(start=-0.5),
                scale=(0.06, 1, 0.06),
                color=rgb32(55, 65, 75),
            ),
            'axle': Entity(
                parent=scene,
                model=Cylinder(start=-0.5),
                scale=(0.06, 1, 0.06),
                color=rgb32(115, 125, 135),
            ),
        }
    )

physics_world.attachVehicle(vehicle)

terrain_particles = []
for _ in range(DUST_PARTICLE_COUNT):
    particle_entity = Entity(
        parent=scene,
        model='sphere',
        scale=0.1,
        color=rgba32(150, 125, 95, 0),
        enabled=False,
        unlit=True,
    )
    terrain_particles.append(
        {
            'entity': particle_entity,
            'life': 0.0,
            'max_life': 1.0,
            'velocity': Vec3(0, 0, 0),
            'base_scale': Vec3(0.1, 0.1, 0.1),
            'base_alpha': 0.0,
        }
    )
terrain_particle_cursor = 0

camera.position = initial_camera_position
camera.rotation = Vec3(22, 0, 0)
camera.fov = 66
initial_camera_rotation = Vec3(camera.rotation)
initial_camera_fov = camera.fov

speed_text = Text(text='Sebesség: 0 km/h', position=(-0.75, 0.45), scale=0.5, color=white)
damage_text = Text(text='Sérülés: 0%', position=(-0.75, 0.43), scale=0.6, color=white)
Text(
    text='UP: gáz | DOWN: fék/hátra | LEFT/RIGHT: kormányzás | F2: újrakezd | Tartsd F1: repülés',
    position=(-0.75, 0.41),
    scale=0.7,
    color=white,
)
crash_text = Text(
    text='A JÁRMŰ ÖSSZETÖRT',
    origin=(0, 0),
    position=(0, 0.1),
    scale=2.5,
    color=rgb32(255, 80, 55),
    enabled=False,
)

damage = 0
broken = False
started = False
flight_active = False
was_chassis_contacting = False
crash_cooldown = 0
collision_slowdown = 0.0
damage_arm_timer = DAMAGE_ARM_DELAY
wrap_grace_timer = 0.0


def restart_game():
    global damage, broken, started, flight_active, was_chassis_contacting, crash_cooldown
    global collision_slowdown, damage_arm_timer, wrap_grace_timer
    global terrain_particle_cursor

    chassis_body.clearForces()
    chassis_body.setLinearVelocity(PandaVec3(0, 0, 0))
    chassis_body.setAngularVelocity(PandaVec3(0, 0, 0))
    chassis_node.setPos(
        initial_car_position.x,
        initial_car_position.y,
        initial_car_position.z,
    )
    chassis_node.setHpr(0, 0, 0)
    chassis_body.setActive(True)
    vehicle.resetSuspension()

    for wheel_index, wheel in enumerate(vehicle_wheels):
        vehicle.setBrake(PARKING_BRAKE_FORCE, wheel_index)
        vehicle.setSteeringValue(0, wheel_index)
        vehicle.applyEngineForce(0, wheel_index)
        wheel.setDeltaRotation(0)
        wheel.setRotation(0)

    for parts in suspension_visuals:
        wheel = vehicle_wheels[parts['wheel_index']]
        wheel.setSuspensionStiffness(parts['original_suspension_stiffness'])
        wheel.setMaxSuspensionForce(parts['original_max_suspension_force'])
        wheel.setWheelsDampingCompression(parts['original_compression_damping'])
        parts['previous_suspension_length'] = None
        parts['impact_cooldown'] = 0.0
        parts['impact_visual'] = 0.0
        parts['compression'] = 0.0
        parts['smoothed_wheel_local_position'] = None
        parts['collapsed'] = False
        parts['particle_timer'] = 0.0
        parts['wheel_model'].rotation_z = 0
        parts['wheel_model'].scale_y = 1

    body_dents.clear()
    body_mesh.vertices = [
        Vec3(vertex.x, vertex.y, vertex.z) for vertex in original_body_vertices
    ]
    body_mesh.generate_normals(smooth=True)
    for particle in terrain_particles:
        particle['entity'].enabled = False
        particle['life'] = 0.0
    terrain_particle_cursor = 0

    damage = 0
    broken = False
    started = False
    flight_active = False
    was_chassis_contacting = False
    crash_cooldown = 0
    collision_slowdown = 0.0
    damage_arm_timer = DAMAGE_ARM_DELAY
    wrap_grace_timer = 0.0
    car_body.color = initial_car_body_color
    crash_text.enabled = False
    speed_text.text = 'Sebesség: 0 km/h'
    damage_text.text = 'Sérülés: 0%'
    camera.position = initial_camera_position
    camera.rotation = initial_camera_rotation
    camera.fov = initial_camera_fov


def input(key):
    global started, flight_active
    if key == 'escape':
        application.quit()
    elif key == 'f2':
        restart_game()
    elif key == 'f1':
        flight_active = True
    elif key == 'f1 up':
        flight_active = False
    elif key in ('up arrow', 'w', 'down arrow', 's'):
        started = True


def position_suspension_link(link, start, end):
    direction = end - start
    length = direction.length()
    if length <= 0.001:
        link.enabled = False
        return

    link.enabled = True
    link.position = (start + end) / 2
    link.scale_y = length
    link.look_at(link.position + direction, axis='up')


def collapse_wheel_suspension(parts):
    if parts['collapsed']:
        return

    wheel = vehicle_wheels[parts['wheel_index']]
    parts['collapsed'] = True
    wheel.setSuspensionStiffness(
        max(4, parts['original_suspension_stiffness'] * 0.625)
    )
    wheel.setMaxSuspensionForce(
        max(500, parts['original_max_suspension_force'] * 0.525)
    )
    wheel.setWheelsDampingCompression(
        max(0.8, parts['original_compression_damping'] * 0.545)
    )


def register_wheel_impact(parts, severity, side, forward_side, chassis_rotation):
    global collision_slowdown, damage, broken

    parts['impact_cooldown'] = 0.85
    parts['impact_visual'] = max(parts['impact_visual'], severity)
    collision_slowdown = max(collision_slowdown, severity)
    if severity * 0.8 >= WHEEL_DENT_SEVERITY_THRESHOLD:
        damage = min(100, damage + max(1, int(severity * 1)))
        damage_text.text = f'Sérülés: {damage}%'
        dent_body(
            Vec3(parts['wheel_x'] * 0.72, -0.02, parts['wheel_z']),
            severity,
        )
    if severity >= SUSPENSION_COLLAPSE_SEVERITY_THRESHOLD and damage > 50:
        collapse_wheel_suspension(parts)
    if damage >= 100:
        broken = True
        crash_text.enabled = True
        car_body.color = rgb32(35, 55, 90)

    velocity = chassis_body.getLinearVelocity()
    planar_velocity = PandaVec3(velocity.x, 0, velocity.z)
    planar_speed = planar_velocity.length()
    if planar_speed > 0.1:
        speed_reduction = min(planar_speed, 1.8 * severity)
        impulse = planar_velocity.normalized() * (
                -chassis_body.getMass() * speed_reduction
        )
        chassis_body.applyCentralImpulse(impulse)

    local_torque_impulse = PandaVec3(
        forward_side * 100 * severity,
        0,
        -side * 220 * severity,
    )
    chassis_body.applyTorqueImpulse(chassis_rotation.xform(local_torque_impulse))


def update_suspension_visuals(dt):
    chassis_position = chassis_node.getPos(render)
    chassis_rotation = chassis_node.getQuat(render)
    visual_follow = 1 - exp(-SUSPENSION_VISUAL_SMOOTHING * dt)

    def chassis_point(local_point):
        offset = chassis_rotation.xform(PandaVec3(*local_point))
        return Vec3(
            chassis_position.x + offset.x,
            chassis_position.y + offset.y,
            chassis_position.z + offset.z,
        )

    def chassis_vector(local_vector):
        offset = chassis_rotation.xform(PandaVec3(*local_vector))
        return Vec3(offset.x, offset.y, offset.z)

    for parts in suspension_visuals:
        wheel_x = parts['wheel_x']
        wheel_z = parts['wheel_z']
        side = 1 if wheel_x > 0 else -1
        forward_side = 1 if wheel_z > 0 else -1
        wheel = vehicle_wheels[parts['wheel_index']]
        raycast = wheel.getRaycastInfo()
        rest_length = wheel.getSuspensionRestLength()
        max_travel = max(wheel.getMaxSuspensionTravelCm() / 100, 0.01)
        parts['impact_cooldown'] = max(0, parts['impact_cooldown'] - dt)
        parts['impact_visual'] *= exp(-4 * dt)

        compression = 0
        if raycast.isInContact():
            suspension_length = raycast.getSuspensionLength()
            compression = max(
                0,
                min(1, (rest_length - suspension_length) / max_travel),
            )
            previous_length = parts['previous_suspension_length']
            if (
                    previous_length is not None
                    and (started or flight_active)
                    and damage_arm_timer <= 0
                    and wrap_grace_timer <= 0
                    and parts['impact_cooldown'] == 0
            ):
                compression_distance = previous_length - suspension_length
                compression_speed = compression_distance / max(dt, 1 / 120)
                if (
                        compression_distance > WHEEL_IMPACT_DISTANCE_THRESHOLD
                        and compression_speed > WHEEL_IMPACT_SPEED_THRESHOLD
                ):
                    severity = min(1, max(0, (compression_speed - 1.5) / 4.5))
                    register_wheel_impact(
                        parts,
                        severity,
                        side,
                        forward_side,
                        chassis_rotation,
                    )
            parts['previous_suspension_length'] = suspension_length
        else:
            parts['previous_suspension_length'] = rest_length + max_travel

        parts['compression'] += (compression - parts['compression']) * visual_follow
        collapse_amount = 1 if parts['collapsed'] else 0
        parts['wheel_model'].rotation_z = side * (
                parts['impact_visual'] * 8 + collapse_amount * 6
        )
        parts['wheel_model'].scale_y = (
                1
                - 0.05 * max(parts['compression'], parts['impact_visual'])
                - 0.07 * collapse_amount
        )

        wheel_world_position = parts['wheel_visual'].world_position
        wheel_local_position = chassis_node.getRelativePoint(
            render,
            PandaPoint3(
                wheel_world_position.x,
                wheel_world_position.y,
                wheel_world_position.z,
            ),
        )
        wheel_local_position = Vec3(
            wheel_local_position.x,
            wheel_local_position.y,
            wheel_local_position.z,
        )
        smoothed_wheel_position = parts['smoothed_wheel_local_position']
        if smoothed_wheel_position is None:
            smoothed_wheel_position = wheel_local_position
        else:
            smoothed_wheel_position += (
                wheel_local_position - smoothed_wheel_position
            ) * visual_follow
        parts['smoothed_wheel_local_position'] = smoothed_wheel_position
        wheel_position = chassis_point(
            (
                smoothed_wheel_position.x,
                smoothed_wheel_position.y,
                smoothed_wheel_position.z,
            )
        )
        axle_hub = wheel_position + chassis_vector((-side * 0.14, 0, 0))

        shock_top = chassis_point((wheel_x * 0.52, 0.03, wheel_z * 0.78))
        shock_bottom = wheel_position + chassis_vector((-side * 0.27, 0.20, 0))
        shock_split = shock_top + (shock_bottom - shock_top) * 0.56
        position_suspension_link(parts['shock'], shock_top, shock_split)
        position_suspension_link(parts['piston'], shock_split, shock_bottom)

        front_hub = wheel_position + chassis_vector(
            (-side * 0.27, 0.02, forward_side * 0.10)
        )
        rear_hub = wheel_position + chassis_vector(
            (-side * 0.27, 0.02, -forward_side * 0.10)
        )
        front_pivot = chassis_point(
            (wheel_x * 0.45, -0.22, wheel_z + forward_side * 0.25)
        )
        rear_pivot = chassis_point(
            (wheel_x * 0.45, -0.22, wheel_z - forward_side * 0.25)
        )
        position_suspension_link(parts['front_arm'], front_pivot, front_hub)
        position_suspension_link(parts['rear_arm'], rear_pivot, rear_hub)

        differential = chassis_point((0, -0.3, wheel_z * 0.80))
        position_suspension_link(parts['axle'], differential, axle_hub)


def wrap_car_if_needed():
    global was_chassis_contacting, crash_cooldown, wrap_grace_timer

    position = chassis_node.getPos(render)
    boundary = WORLD_HALF
    if abs(position.x) <= boundary and abs(position.z) <= boundary:
        return

    new_x = (position.x + boundary) % WORLD_SIZE - boundary
    new_z = (position.z + boundary) % WORLD_SIZE - boundary
    height_above_terrain = max(
        0.75,
        position.y - terrain_height(new_x, new_z),
    )
    new_y = terrain_height(new_x, new_z) + height_above_terrain
    chassis_node.setPos(new_x, new_y, new_z)
    chassis_body.setActive(True)
    vehicle.resetSuspension()
    wrap_offset = Vec3(
        new_x - position.x,
        new_y - position.y,
        new_z - position.z,
    )
    camera.position += wrap_offset
    for particle in terrain_particles:
        if particle['entity'].enabled:
            particle['entity'].position += wrap_offset

    was_chassis_contacting = False
    crash_cooldown = max(crash_cooldown, 0.75)
    wrap_grace_timer = 0.75
    for parts in suspension_visuals:
        parts['previous_suspension_length'] = None


def terrain_particle_style(world_x, world_z):
    local_x = (world_x + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
    local_z = (world_z + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
    column = round((local_x / WORLD_SIZE + 0.5) * (MAP_RESOLUTION - 1))
    row = round((0.5 - local_z / WORLD_SIZE) * (MAP_RESOLUTION - 1))
    column = max(0, min(MAP_RESOLUTION - 1, column))
    row = max(0, min(MAP_RESOLUTION - 1, row))
    red, green, blue = map_image.getpixel((column, row))

    is_water = blue > red * 1.3 and blue > green * 1.15
    is_brown = red > green + 8 and green > blue + 8 and blue > 15 and red < 215
    is_grass = green > red + 8 and green > blue + 6
    if is_water:
        color = rgba32(85, 175, 240, 175)
        base_scale = Vec3(0.055, 0.075, 0.055)
        lifetime = 0.2
    elif is_grass:
        color = rgba32(100, 165, 75, 145)
        base_scale = Vec3(0.055, 0.14, 0.045)
        lifetime = 0.2
    elif is_brown:
        color = rgba32(166, 128, 88, 130)
        base_scale = Vec3(0.13, 0.10, 0.13)
        lifetime = 0.2
    else:
        color = rgba32(
            min(255, int(red * 0.75 + 64)),
            min(255, int(green * 0.75 + 64)),
            min(255, int(blue * 0.75 + 64)),
            125,
        )
        base_scale = Vec3(0.10, 0.08, 0.10)
        lifetime = 0.2
    return color, base_scale, lifetime


def emit_terrain_particle(parts, speed_kmh, chassis_rotation):
    global terrain_particle_cursor

    wheel_position = parts['wheel_visual'].world_position
    color, base_scale, lifetime = terrain_particle_style(
        wheel_position.x,
        wheel_position.z,
    )
    travel_sign = 1 if speed_kmh >= 0 else -1
    backward = chassis_rotation.xform(PandaVec3(0, 0, -travel_sign))
    sideways = chassis_rotation.xform(
        PandaVec3(1 if parts['wheel_x'] > 0 else -1, 0, 0)
    )
    backward = Vec3(backward.x, backward.y, backward.z)
    sideways = Vec3(sideways.x, sideways.y, sideways.z)
    vehicle_velocity = chassis_body.getLinearVelocity()
    particle_velocity = (
            Vec3(vehicle_velocity.x, vehicle_velocity.y, vehicle_velocity.z) * 0.08
            + backward * uniform(0.35, 1.1)
            + sideways * uniform(0.2, 0.65)
            + Vec3(0, uniform(0.55, 1.25), 0)
    )

    particle = terrain_particles[terrain_particle_cursor]
    terrain_particle_cursor = (terrain_particle_cursor + 1) % len(terrain_particles)
    particle['entity'].position = (
            wheel_position + backward * 0.18 + Vec3(0, -0.23, 0)
    )
    particle['entity'].color = color
    particle['entity'].enabled = True
    particle['life'] = lifetime * uniform(0.8, 1.2)
    particle['max_life'] = particle['life']
    particle['velocity'] = particle_velocity
    scale_factor = uniform(0.75, 1.25)
    particle['base_scale'] = base_scale * scale_factor
    particle['base_alpha'] = color[3]
    particle['entity'].scale = particle['base_scale']


def update_terrain_particles(dt, speed_kmh):
    if started and abs(speed_kmh) > 5:
        chassis_rotation = chassis_node.getQuat(render)
        for parts in suspension_visuals:
            parts['particle_timer'] -= dt
            wheel = vehicle_wheels[parts['wheel_index']]
            if parts['particle_timer'] <= 0 and wheel.getRaycastInfo().isInContact():
                emit_terrain_particle(parts, speed_kmh, chassis_rotation)
                speed_factor = min(abs(speed_kmh) / 100, 1)
                parts['particle_timer'] = 0.06 + 0.03 * (1 - speed_factor)
    else:
        for parts in suspension_visuals:
            parts['particle_timer'] = 0

    for particle in terrain_particles:
        if not particle['entity'].enabled:
            continue
        particle['life'] -= dt
        if particle['life'] <= 0:
            particle['entity'].enabled = False
            continue

        age = 1 - particle['life'] / particle['max_life']
        particle['velocity'].y -= 3 * dt
        particle['entity'].position += particle['velocity'] * dt
        particle['entity'].scale = particle['base_scale'] * (1 + age * 6)
        particle['entity'].alpha = particle['base_alpha'] * (1 - age)


def update_crash_state(dt, incoming_speed=0):
    global damage, broken, was_chassis_contacting, crash_cooldown, collision_slowdown
    crash_cooldown = max(0, crash_cooldown - dt)
    contacts = physics_world.contactTest(chassis_body).getContacts()
    is_contacting = bool(contacts)

    if (
            is_contacting
            and not was_chassis_contacting
            and crash_cooldown == 0
            and damage_arm_timer <= 0
            and wrap_grace_timer <= 0
    ):
        impact_speed = max(incoming_speed, chassis_body.getLinearVelocity().length())
        strongest_contact = max(
            contacts,
            key=lambda contact: contact.getManifoldPoint().getAppliedImpulse(),
        )
        impact_impulse = strongest_contact.getManifoldPoint().getAppliedImpulse()
        impact = max(impact_speed, impact_impulse / chassis_body.getMass())
        if impact > CRASH_SPEED_THRESHOLD:
            severity = max(
                0.2,
                min(1, (impact - CRASH_SPEED_THRESHOLD) / 12),
            )
            damage = min(
                100,
                damage + max(1, int((impact - CRASH_SPEED_THRESHOLD) * 2)),
            )
            damage_text.text = f'Sérülés: {damage}%'
            crash_cooldown = 1.0
            collision_slowdown = max(collision_slowdown, severity)

            manifold = strongest_contact.getManifoldPoint()
            point_a = manifold.getPositionWorldOnA()
            point_b = manifold.getPositionWorldOnB()
            world_contact = PandaPoint3(
                (point_a.x + point_b.x) / 2,
                (point_a.y + point_b.y) / 2,
                (point_a.z + point_b.z) / 2,
            )
            local_contact = chassis_node.getRelativePoint(render, world_contact)
            local_contact = Vec3(local_contact.x, local_contact.y, local_contact.z)
            dent_body(local_contact, severity)

            nearest_wheel = min(
                suspension_visuals,
                key=lambda parts: (
                        (parts['wheel_x'] - local_contact.x) ** 2
                        + (parts['wheel_z'] - local_contact.z) ** 2
                ),
            )
            if severity >= SUSPENSION_COLLAPSE_SEVERITY_THRESHOLD and damage > 50:
                collapse_wheel_suspension(nearest_wheel)

            if damage >= 100:
                broken = True
                crash_text.enabled = True
                car_body.color = rgb32(35, 55, 90)
                chassis_body.applyCentralImpulse(PandaVec3(0, 2, 0))

    was_chassis_contacting = is_contacting


def update():
    global started, collision_slowdown, damage_arm_timer, wrap_grace_timer
    dt = min(time.dt, 1 / 30)
    collision_slowdown = max(0, collision_slowdown - dt * 0.25)
    damage_arm_timer = max(0, damage_arm_timer - dt)
    wrap_grace_timer = max(0, wrap_grace_timer - dt)
    speed_kmh = vehicle.getCurrentSpeedKmHour()
    accelerating = held_keys['up arrow'] or held_keys['w']
    reversing = held_keys['down arrow'] or held_keys['s']
    steering = int(bool(held_keys['right arrow'] or held_keys['d'])) - int(
        bool(held_keys['left arrow'] or held_keys['a'])
    )

    engine_force = 0
    brake_force = PARKING_BRAKE_FORCE if not started and not flight_active else 8
    if started and not broken:
        if accelerating and speed_kmh < MAX_FORWARD_SPEED_KMH:
            engine_force = -ENGINE_FORCE
            brake_force = 0
        elif reversing and speed_kmh > 1:
            brake_force = BRAKE_FORCE
        elif reversing and speed_kmh > -MAX_REVERSE_SPEED_KMH:
            engine_force = REVERSE_FORCE
            brake_force = 0

    steering_scale = max(0.7, 1 - abs(speed_kmh) / 120)
    if speed_kmh < 0:
        steering_scale *= REVERSE_STEERING_SCALE
    steering_angle = steering * STEERING_ANGLE * steering_scale
    if broken:
        steering_angle = 0
        brake_force = BRAKE_FORCE
    engine_force = int(engine_force * (1 - 0.65 * collision_slowdown))
    if flight_active:
        brake_force = 0
        chassis_body.applyCentralForce(
            PandaVec3(0, chassis_body.getMass() * FLIGHT_ACCELERATION, 0)
        )
        local_torque = chassis_node.getQuat(render).xform(FLIGHT_TORQUE)
        chassis_body.applyTorque(local_torque)

    for wheel_index in range(4):
        vehicle.setBrake(brake_force, wheel_index)
        if wheel_index < 2:
            vehicle.setSteeringValue(steering_angle, wheel_index)
        else:
            vehicle.applyEngineForce(engine_force, wheel_index)

    if steering and abs(speed_kmh) > 2:
        travel_direction = 1 if speed_kmh > 0 else -1
        speed_factor = min(abs(speed_kmh) / 20, 1)
        chassis_body.applyTorque(
            PandaVec3(0, steering * STEERING_ASSIST_TORQUE * speed_factor * travel_direction, 0)
        )

    wrap_car_if_needed()
    incoming_speed = chassis_body.getLinearVelocity().length()
    physics_world.doPhysics(dt, 8, 1 / 120)
    update_suspension_visuals(dt)
    update_crash_state(dt, incoming_speed)

    speed_kmh = vehicle.getCurrentSpeedKmHour()
    update_terrain_particles(dt, speed_kmh)
    speed_text.text = f'Sebesség: {int(abs(speed_kmh))} km/h'

    position = chassis_node.getPos(render)
    forward_vector = chassis_node.getQuat(render).xform(PandaVec3(0, 0, 1))
    forward = Vec3(forward_vector.x, 0, forward_vector.z)
    if forward.length():
        forward = forward.normalized()
    right = Vec3(forward.z, 0, -forward.x)
    shadow_vertices = []
    for row in range(SHADOW_ROWS):
        local_z = SHADOW_LENGTH / 2 - row * SHADOW_LENGTH / (SHADOW_ROWS - 1)
        for column in range(SHADOW_COLUMNS):
            local_x = -SHADOW_WIDTH / 2 + column * SHADOW_WIDTH / (SHADOW_COLUMNS - 1)
            world_x = position.x + right.x * local_x + forward.x * local_z
            world_z = position.z + right.z * local_x + forward.z * local_z
            shadow_vertices.append(
                Vec3(
                    world_x,
                    terrain_surface_height(world_x, world_z) + 0.04,
                    world_z,
                )
            )
    car_shadow_mesh.vertices = shadow_vertices
    car_shadow_mesh.generate()
    camera_target = Vec3(
        position.x - forward.x * CAMERA_DISTANCE,
        position.y + CAMERA_HEIGHT,
        position.z - forward.z * CAMERA_DISTANCE,
    )
    follow_amount = 1 - exp(-CAMERA_FOLLOW_SPEED * dt)
    turn_amount = 1 - exp(-CAMERA_TURN_FOLLOW_SPEED * dt)
    camera.position += (camera_target - camera.position) * follow_amount
    camera_heading = degrees(atan2(forward.x, forward.z))
    camera.rotation_x += (22 - camera.rotation_x) * follow_amount
    camera.rotation_y = smooth_angle(camera.rotation_y, camera_heading, turn_amount)
    camera.rotation_z += (0 - camera.rotation_z) * follow_amount


app.run()
