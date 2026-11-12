"""Vehicle physics, visuals, suspension, damage, and particle effects."""
from math import cos, exp, pi, sin
from random import uniform
from panda3d.bullet import BulletBoxShape, BulletRigidBodyNode, BulletVehicle
from panda3d.core import Point3 as PandaPoint3, Vec3 as PandaVec3, TransformState
from ursina import *
from ursina.color import black, rgb32, rgba32

from .config import *
from .damage import BodyDeformation, BumperDeformation


class OffRoadVehicle:
    def __init__(
        self, physics_world, terrain, game, body_color=None, position=None,
        damage_config=DAMAGE_CONFIG,
    ):
        self.physics_world = physics_world
        self.terrain = terrain
        self.game = game
        self.damage = 0
        self.broken = False
        self.was_chassis_contacting = False
        self.crash_cooldown = 0.0
        self.collision_slowdown = 0.0
        self.damage_arm_timer = DAMAGE_ARM_DELAY
        self.damage_config = damage_config
        self.deformation = BodyDeformation(damage_config)
        self.deformable_meshes = []
        self.damage_time = 0.0
        self.paint_color = body_color if body_color is not None else rgb32(25, 105, 235)
        chassis_body = BulletRigidBodyNode(f'offroad-chassis-{id(self)}')
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
        chassis_body.addShape(
            BulletBoxShape(PandaVec3(0.55, 0.28, 0.70)),
            TransformState.makePos(PandaVec3(0, 0.62, -0.20)),
        )
        chassis_body.setFriction(0.8)
        chassis_body.setRestitution(0.05)

        initial_car_position = (
            Vec3(0, terrain.height(0, 0) + 2, 0)
            if position is None
            else Vec3(*position)
        )
        initial_camera_position = Vec3(
            0,
            terrain.height(0, 0) + CAMERA_HEIGHT,
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
                    Vec3(world_x, terrain.surface_height(world_x, world_z) + 0.04, world_z)
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

        base_body_sections = (
            (-1.34, 0.60, 0.54, -0.12, 0.22),
            (-1.16, 0.74, 0.66, -0.18, 0.40),
            (-0.72, 0.80, 0.71, -0.20, 0.42),
            (0.48, 0.80, 0.72, -0.20, 0.38),
            (1.04, 0.72, 0.66, -0.16, 0.31),
            (1.34, 0.60, 0.56, -0.12, 0.25),
        )
        body_sections = []
        for start, end in zip(base_body_sections, base_body_sections[1:]):
            body_sections.append(start)
            for step in (1, 2):
                fraction = step / 3
                body_sections.append(
                    tuple(
                        first + (last - first) * fraction
                        for first, last in zip(start, end)
                    )
                )
        body_sections.append(base_body_sections[-1])
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

        body_mesh = Mesh(vertices=body_vertices, triangles=body_triangles, static=False)
        body_mesh.generate_normals(smooth=True)
        car_body = Entity(
            parent=car_visual,
            model=body_mesh,
            color=self.paint_color,
            double_sided=True,
        )
        initial_car_body_color = car_body.color
        original_body_vertices = tuple(
            Vec3(vertex.x, vertex.y, vertex.z) for vertex in body_mesh.vertices
        )
        self.deformable_meshes.append((body_mesh, original_body_vertices))
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
        cabin_mesh = Mesh(vertices=cabin_vertices, triangles=cabin_triangles, static=False)
        cabin_mesh.generate_normals(smooth=False)
        cabin_entity = Entity(
            parent=car_visual,
            model=cabin_mesh,
            color=self.paint_color,
            double_sided=True,
        )
        self.deformable_meshes.append((cabin_mesh, tuple(Vec3(v) for v in cabin_vertices)))
        mesh_entities = [car_body, cabin_entity]

        def create_window(points):
            window_mesh = Mesh(
                vertices=[Vec3(*point) for point in points],
                triangles=(0, 1, 2, 0, 2, 3),
                static=False,
            )
            window_mesh.generate_normals(smooth=False)
            window_entity = Entity(
                parent=car_visual,
                model=window_mesh,
                color=rgb32(24, 55, 82),
                double_sided=True,
            )
            mesh_entities.append(window_entity)
            self.deformable_meshes.append(
                (window_mesh, tuple(Vec3(*point) for point in points))
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
            color=self.paint_color,
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

        bumper_meshes = []
        bumper_sides = 8
        bumper_sections = 13
        bumper_radius = 0.06
        for bumper_z in (-1.43, 1.43):
            bumper_vertices = []
            bumper_triangles = []
            for section in range(bumper_sections):
                x = -0.8 + 1.6 * section / (bumper_sections - 1)
                for side in range(bumper_sides):
                    angle = 2 * pi * side / bumper_sides
                    bumper_vertices.append(
                        Vec3(
                            x,
                            sin(angle) * bumper_radius,
                            cos(angle) * bumper_radius,
                        )
                    )
            for section in range(bumper_sections - 1):
                for side in range(bumper_sides):
                    next_side = (side + 1) % bumper_sides
                    first = section * bumper_sides + side
                    next_first = section * bumper_sides + next_side
                    second = first + bumper_sides
                    next_second = next_first + bumper_sides
                    bumper_triangles.extend(
                        (first, next_first, next_second, first, next_second, second)
                    )
            bumper_mesh = Mesh(
                vertices=bumper_vertices,
                triangles=bumper_triangles,
                static=False,
            )
            bumper_mesh.generate_normals(smooth=True)
            bumper_entity = Entity(
                parent=car_visual,
                model=bumper_mesh,
                position=(0, 0.0, bumper_z),
                color=rgb32(145, 155, 165),
                double_sided=True,
            )
            bumper_meshes.append(
                {
                    'mesh': bumper_mesh,
                    'original_vertices': tuple(
                        Vec3(vertex.x, vertex.y, vertex.z)
                        for vertex in bumper_vertices
                    ),
                    'forward_sign': 1 if bumper_z > 0 else -1,
                    'entity': bumper_entity,
                    'deformation': BumperDeformation(
                        1 if bumper_z > 0 else -1, damage_config,
                    ),
                }
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

        bumper_entities = [bumper['entity'] for bumper in bumper_meshes]
        self.body_attachments = [
            (entity, Vec3(entity.position), Vec3(entity.scale))
            for entity in car_visual.children
            if entity not in mesh_entities and entity not in bumper_entities
        ]
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
        self.physics_world = physics_world
        self.terrain = terrain
        self.initial_car_position = initial_car_position
        self.initial_camera_position = initial_camera_position
        self.chassis_body = chassis_body
        self.chassis_node = chassis_node
        self.vehicle = vehicle
        self.car_visual = car_visual
        self.car_shadow_mesh = car_shadow_mesh
        self.car_shadow = car_shadow
        self.body_mesh = body_mesh
        self.car_body = car_body
        self.initial_car_body_color = initial_car_body_color
        self.original_body_vertices = original_body_vertices
        self.bumper_meshes = bumper_meshes
        self.wheel_visuals = wheel_visuals
        self.vehicle_wheels = vehicle_wheels
        self.suspension_visuals = suspension_visuals
        self.terrain_particles = terrain_particles
        self.terrain_particle_cursor = terrain_particle_cursor
        self.SHADOW_COLUMNS = SHADOW_COLUMNS
        self.SHADOW_ROWS = SHADOW_ROWS
        self.SHADOW_WIDTH = SHADOW_WIDTH
        self.SHADOW_LENGTH = SHADOW_LENGTH

    def dent_body(self, local_position, severity, outward=None):
        zone = self.deformation.impact(
            local_position, severity, self.damage, outward,
        )
        if self.damage < self.damage_config.body_damage_threshold:
            return
        if zone in ('front', 'rear'):
            self.bend_bumper(local_position, severity)
        self.refresh_bodywork()

    def refresh_bodywork(self):
        for mesh, original_vertices in self.deformable_meshes:
            mesh.vertices = [self.deformation.deform(v) for v in original_vertices]
            mesh.generate_normals(smooth=True)
        for entity, position, scale in self.body_attachments:
            entity.position = self.deformation.deform(position)
            dimensions = []
            for axis in (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)):
                extent = axis * 0.05
                size = (
                    self.deformation.deform(position + extent)
                    - self.deformation.deform(position - extent)
                ).length() / 0.1
                dimensions.append(max(0.35, min(1.3, size)))
            entity.scale = Vec3(
                scale.x * dimensions[0],
                scale.y * dimensions[1],
                scale.z * dimensions[2],
            )
        self.car_visual.rotation_z = self.deformation.roll
        for bumper in self.bumper_meshes:
            self.refresh_bumper(bumper)

    def bend_bumper(self, local_position, severity):
        forward_sign = 1 if local_position.z >= 0 else -1
        for bumper in self.bumper_meshes:
            if bumper['forward_sign'] == forward_sign:
                bumper['deformation'].impact(local_position, severity)
                self.refresh_bumper(bumper)

    def refresh_bumper(self, bumper):
        base = Vec3(0, 0, bumper['forward_sign'] * 1.43)
        bumper['mesh'].vertices = [
            self.deformation.deform(vertex + base) - base
            + bumper['deformation'].deform(vertex, self.damage_time) - vertex
            for vertex in bumper['original_vertices']
        ]
        bumper['mesh'].generate_normals(smooth=True)

    def update_bodywork(self, dt):
        self.damage_time += dt
        for bumper in self.bumper_meshes:
            if bumper['deformation'].broken_mount:
                self.refresh_bumper(bumper)

    def reset_damage(self):
        self.damage = 0
        self.broken = False
        self.damage_time = 0
        self.deformation.reset()
        self.refresh_bodywork()
        for entity, position, scale in self.body_attachments:
            entity.position = position
            entity.scale = scale
        for bumper in self.bumper_meshes:
            bumper['deformation'].reset()
            self.refresh_bumper(bumper)
        self.car_body.color = self.initial_car_body_color

    def position_suspension_link(self, link, start, end):
        direction = end - start
        length = direction.length()
        if length <= 0.001:
            link.enabled = False
            return

        link.enabled = True
        link.position = (start + end) / 2
        link.scale_y = length
        link.look_at(link.position + direction, axis='up')

    def collapse_wheel_suspension(self, parts):
        if parts['collapsed']:
            return

        wheel = self.vehicle_wheels[parts['wheel_index']]
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

    def register_wheel_impact(self, parts, severity, side, forward_side, chassis_rotation):
        is_player_car = self.game.car is self
        parts['impact_cooldown'] = 0.85
        parts['impact_visual'] = max(parts['impact_visual'], severity)
        if is_player_car:
            self.game.collision_slowdown = max(self.game.collision_slowdown, severity)
        else:
            self.collision_slowdown = max(self.collision_slowdown, severity)
        damage = self.game.damage if is_player_car else self.damage
        speed_kmh = self.chassis_body.getLinearVelocity().length() * 3.6
        can_damage = speed_kmh >= self.damage_config.damage_speed_threshold_kmh
        if can_damage and severity * 0.8 >= WHEEL_DENT_SEVERITY_THRESHOLD:
            damage = min(100, damage + max(1, int(severity * 4)))
            if is_player_car:
                self.game.damage = damage
                self.damage = damage
                self.game.damage_text.text = f'Sérülés: {damage}%'
            else:
                self.damage = damage
            self.dent_body(
                Vec3(parts['wheel_x'] * 0.72, -0.02, parts['wheel_z']),
                severity,
            )
        if (
            can_damage
            and severity >= self.damage_config.suspension_impact_threshold
            and damage >= self.damage_config.suspension_damage_threshold
        ):
            self.collapse_wheel_suspension(parts)
        if can_damage and damage >= 100:
            self.broken = True
            if is_player_car:
                self.game.broken = True
                self.game.crash_text.enabled = True
            self.car_body.color = rgb32(35, 55, 90)

        velocity = self.chassis_body.getLinearVelocity()
        planar_velocity = PandaVec3(velocity.x, 0, velocity.z)
        planar_speed = planar_velocity.length()
        if planar_speed > 0.1:
            speed_reduction = min(planar_speed, 1.8 * severity)
            impulse = planar_velocity.normalized() * (
                    -self.chassis_body.getMass() * speed_reduction
            )
            self.chassis_body.applyCentralImpulse(impulse)

        local_torque_impulse = PandaVec3(
            forward_side * 100 * severity,
            0,
            -side * 220 * severity,
        )
        self.chassis_body.applyTorqueImpulse(chassis_rotation.xform(local_torque_impulse))

    def update_suspension_visuals(self, dt):
        chassis_position = self.chassis_node.getPos(render)
        chassis_rotation = self.chassis_node.getQuat(render)
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

        for parts in self.suspension_visuals:
            wheel_x = parts['wheel_x']
            wheel_z = parts['wheel_z']
            side = 1 if wheel_x > 0 else -1
            forward_side = 1 if wheel_z > 0 else -1
            wheel = self.vehicle_wheels[parts['wheel_index']]
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
                        and (self.game.started or self.game.flight_active)
                        and (
                            self.game.damage_arm_timer
                            if self.game.car is self
                            else self.damage_arm_timer
                        ) <= 0
                        and (
                            self.game.wrap_grace_timer
                            if self.game.car is self
                            else 0
                        ) <= 0
                        and parts['impact_cooldown'] == 0
                ):
                    compression_distance = previous_length - suspension_length
                    compression_speed = compression_distance / max(dt, 1 / 120)
                    if (
                            compression_distance > WHEEL_IMPACT_DISTANCE_THRESHOLD
                            and compression_speed > WHEEL_IMPACT_SPEED_THRESHOLD
                    ):
                        severity = min(1, max(0, (compression_speed - 1.5) / 4.5))
                        self.register_wheel_impact(
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
            wheel_local_position = self.chassis_node.getRelativePoint(
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
            self.position_suspension_link(parts['shock'], shock_top, shock_split)
            self.position_suspension_link(parts['piston'], shock_split, shock_bottom)

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
            self.position_suspension_link(parts['front_arm'], front_pivot, front_hub)
            self.position_suspension_link(parts['rear_arm'], rear_pivot, rear_hub)

            differential = chassis_point((0, -0.3, wheel_z * 0.80))
            self.position_suspension_link(parts['axle'], differential, axle_hub)

    def update_shadow(self):
        position = self.chassis_node.getPos(render)
        forward_vector = self.chassis_node.getQuat(render).xform(PandaVec3(0, 0, 1))
        forward = Vec3(forward_vector.x, 0, forward_vector.z)
        if forward.length():
            forward = forward.normalized()
        right = Vec3(forward.z, 0, -forward.x)
        shadow_vertices = []
        for row in range(self.SHADOW_ROWS):
            local_z = self.SHADOW_LENGTH / 2 - row * self.SHADOW_LENGTH / (self.SHADOW_ROWS - 1)
            for column in range(self.SHADOW_COLUMNS):
                local_x = -self.SHADOW_WIDTH / 2 + column * self.SHADOW_WIDTH / (self.SHADOW_COLUMNS - 1)
                world_x = position.x + right.x * local_x + forward.x * local_z
                world_z = position.z + right.z * local_x + forward.z * local_z
                shadow_vertices.append(
                    Vec3(
                        world_x,
                        self.terrain.surface_height(world_x, world_z) + 0.04,
                        world_z,
                    )
                )
        self.car_shadow_mesh.vertices = shadow_vertices
        self.car_shadow_mesh.generate()

    def emit_terrain_particle(self, parts, speed_kmh, chassis_rotation):

        wheel_position = parts['wheel_visual'].world_position
        color, base_scale, lifetime = self.terrain.particle_style(
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
        vehicle_velocity = self.chassis_body.getLinearVelocity()
        particle_velocity = (
                Vec3(vehicle_velocity.x, vehicle_velocity.y, vehicle_velocity.z) * 0.08
                + backward * uniform(0.35, 1.1)
                + sideways * uniform(0.2, 0.65)
                + Vec3(0, uniform(0.55, 1.25), 0)
        )

        particle = self.terrain_particles[self.terrain_particle_cursor]
        self.terrain_particle_cursor = (self.terrain_particle_cursor + 1) % len(self.terrain_particles)
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

    def update_terrain_particles(self, dt, speed_kmh):
        if self.game.started and abs(speed_kmh) > 5:
            chassis_rotation = self.chassis_node.getQuat(render)
            for parts in self.suspension_visuals:
                parts['particle_timer'] -= dt
                wheel = self.vehicle_wheels[parts['wheel_index']]
                if parts['particle_timer'] <= 0 and wheel.getRaycastInfo().isInContact():
                    self.emit_terrain_particle(parts, speed_kmh, chassis_rotation)
                    speed_factor = min(abs(speed_kmh) / 100, 1)
                    parts['particle_timer'] = 0.06 + 0.03 * (1 - speed_factor)
        else:
            for parts in self.suspension_visuals:
                parts['particle_timer'] = 0

        for particle in self.terrain_particles:
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
