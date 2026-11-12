"""Game setup and frame-by-frame orchestration."""
from math import atan2, cos, degrees, exp, radians, sin
from panda3d.bullet import BulletWorld
from panda3d.core import Vec3 as PandaVec3
from ursina import *
from ursina import application
from ursina.color import rgb32, white

from .config import *
from .terrain import Terrain
from .vehicle import OffRoadVehicle


def smooth_angle(current, target, amount):
    difference = (target - current + 180) % 360 - 180
    return current + difference * amount


class Game:
    def __init__(self, damage_config=DAMAGE_CONFIG):
        self.app = Ursina()
        window.title = 'Terepj\u00e1r\u00f3 - domborzati p\u00e1lya'
        window.fps_counter.enabled = True
        window.color = rgb32(135, 180, 215)

        self.physics_world = BulletWorld()
        self.physics_world.setGravity(PandaVec3(0, -9.81, 0))
        self.terrain = Terrain(self.physics_world)
        self.car = OffRoadVehicle(
            self.physics_world, self.terrain, self, damage_config=damage_config,
        )
        self.vehicles = [self.car]

        self.initial_camera_position = self.car.initial_camera_position
        camera.position = self.initial_camera_position
        camera.rotation = Vec3(22, 0, 0)
        camera.fov = 66
        self.initial_camera_rotation = Vec3(camera.rotation)
        self.initial_camera_fov = camera.fov

        self.speed_text = Text(text='Sebess\u00e9g: 0 km/h', position=(-0.75, 0.45), scale=0.5, color=white)
        self.damage_text = Text(text='S\u00e9r\u00fcl\u00e9s: 0%', position=(-0.75, 0.43), scale=0.6, color=white)
        Text(text='UP: g\u00e1z | DOWN: f\u00e9k/h\u00e1tra | LEFT/RIGHT: korm\u00e1nyz\u00e1s | F2: \u00fajrakezd | Tartsd F1: rep\u00fcl\u00e9s', position=(-0.75, 0.41), scale=0.7, color=white)
        self.crash_text = Text(text='A J\u00c1RM\u0170 \u00d6SSZET\u00d6RT', origin=(0, 0), position=(0, 0.1), scale=2.5, color=rgb32(255, 80, 55), enabled=False)

        self.damage = 0
        self.broken = False
        self.started = False
        self.flight_active = False
        self.was_chassis_contacting = False
        self.crash_cooldown = 0
        self.collision_slowdown = 0.0
        self.damage_arm_timer = DAMAGE_ARM_DELAY
        self.wrap_grace_timer = 0.0
        self.orbit_active = False
        self.orbit_angle = 0.0
        self.intro_landed = False
        self.intro_settled_time = 0.0
        self.car_held_for_start = False

    def run(self):
        self.app.run()

    def add_car(self, body_color, position=None, damage_config=None):
        if position is None:
            x = len(self.vehicles) * 4
            z = 0
            position = Vec3(x, self.terrain.height(x, z) + 2, z)
        car = OffRoadVehicle(
            self.physics_world,
            self.terrain,
            self,
            body_color=body_color,
            position=position,
            damage_config=(
                self.car.damage_config if damage_config is None else damage_config
            ),
        )
        self.vehicles.append(car)
        return car

    def restart_game(self):

        self.car.chassis_body.setKinematic(False)
        self.car_held_for_start = False
        self.car.chassis_body.clearForces()
        self.car.chassis_body.setLinearVelocity(PandaVec3(0, 0, 0))
        self.car.chassis_body.setAngularVelocity(PandaVec3(0, 0, 0))
        self.car.chassis_node.setPos(
            self.car.initial_car_position.x,
            self.car.initial_car_position.y,
            self.car.initial_car_position.z,
        )
        self.car.chassis_node.setHpr(0, 0, 0)
        self.car.chassis_body.setActive(True)
        self.car.vehicle.resetSuspension()

        for wheel_index, wheel in enumerate(self.car.vehicle_wheels):
            self.car.vehicle.setBrake(PARKING_BRAKE_FORCE, wheel_index)
            self.car.vehicle.setSteeringValue(0, wheel_index)
            self.car.vehicle.applyEngineForce(0, wheel_index)
            wheel.setDeltaRotation(0)
            wheel.setRotation(0)

        for parts in self.car.suspension_visuals:
            wheel = self.car.vehicle_wheels[parts['wheel_index']]
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

        self.car.reset_damage()
        for particle in self.car.terrain_particles:
            particle['entity'].enabled = False
            particle['life'] = 0.0
        self.car.terrain_particle_cursor = 0

        self.damage = 0
        self.broken = False
        self.car.damage = 0
        self.car.broken = False
        self.car.was_chassis_contacting = False
        self.car.crash_cooldown = 0
        self.car.collision_slowdown = 0
        self.car.damage_arm_timer = DAMAGE_ARM_DELAY
        self.started = False
        self.flight_active = False
        self.was_chassis_contacting = False
        self.crash_cooldown = 0
        self.collision_slowdown = 0.0
        self.damage_arm_timer = DAMAGE_ARM_DELAY
        self.wrap_grace_timer = 0.0
        self.crash_text.enabled = False
        self.speed_text.text = 'Sebesség: 0 km/h'
        self.damage_text.text = 'Sérülés: 0%'
        camera.position = self.initial_camera_position
        camera.rotation = self.initial_camera_rotation
        camera.fov = self.initial_camera_fov
        self.orbit_active = False
        self.intro_landed = False
        self.intro_settled_time = 0.0
        self.hold_car_before_start()

    def handle_input(self, key):
        if key == 'escape':
            application.quit()
        elif key == 'f2':
            self.restart_game()
        elif key == 'f1':
            self.flight_active = True
        elif key == 'f1 up':
            self.flight_active = False
        elif key in ('up arrow', 'w', 'down arrow', 's'):
            self.started = True

    def hold_car_before_start(self):
        should_hold = (
            self.intro_landed
            and not self.started
            and not self.flight_active
            and not self.broken
        )
        if should_hold == self.car_held_for_start:
            return
        body = self.car.chassis_body
        body.clearForces()
        body.setLinearVelocity(PandaVec3(0, 0, 0))
        body.setAngularVelocity(PandaVec3(0, 0, 0))
        body.setKinematic(should_hold)
        body.setActive(True)
        self.car_held_for_start = should_hold

    def wrap_car_if_needed(self):

        position = self.car.chassis_node.getPos(render)
        boundary = WORLD_HALF
        if abs(position.x) <= boundary and abs(position.z) <= boundary:
            return

        new_x = (position.x + boundary) % WORLD_SIZE - boundary
        new_z = (position.z + boundary) % WORLD_SIZE - boundary
        height_above_terrain = max(
            0.75,
            position.y - self.terrain.height(new_x, new_z),
        )
        new_y = self.terrain.height(new_x, new_z) + height_above_terrain
        self.car.chassis_node.setPos(new_x, new_y, new_z)
        self.car.chassis_body.setActive(True)
        self.car.vehicle.resetSuspension()
        wrap_offset = Vec3(
            new_x - position.x,
            new_y - position.y,
            new_z - position.z,
        )
        camera.position += wrap_offset
        for particle in self.car.terrain_particles:
            if particle['entity'].enabled:
                particle['entity'].position += wrap_offset

        self.was_chassis_contacting = False
        self.crash_cooldown = max(self.crash_cooldown, 0.75)
        self.wrap_grace_timer = 0.75
        for parts in self.car.suspension_visuals:
            parts['previous_suspension_length'] = None

    def update_crash_state(self, dt, incoming_velocity=None, car=None):
        car = self.car if car is None else car
        is_player_car = car is self.car
        state = self if is_player_car else car
        config = car.damage_config
        state.crash_cooldown = max(0, state.crash_cooldown - dt)
        if not is_player_car:
            car.damage_arm_timer = max(0, car.damage_arm_timer - dt)
        grace = self.wrap_grace_timer if is_player_car else 0
        if incoming_velocity is None:
            incoming_velocity = car.chassis_body.getLinearVelocity()

        impacts = []
        is_contacting = False
        # Persistent manifolds retain solver impulses; contactTest creates a fresh query.
        for manifold in self.physics_world.getManifolds():
            node_a, node_b = manifold.getNode0(), manifold.getNode1()
            if car.chassis_body not in (node_a, node_b):
                continue
            car_is_a = node_a == car.chassis_body
            other = node_b if car_is_a else node_a
            for point in manifold.getManifoldPoints():
                if point.getDistance() > 0.05:
                    continue
                is_contacting = True
                outward = point.getNormalWorldOnB()
                if car_is_a:
                    outward = -outward
                world_point = (
                    point.getPositionWorldOnA()
                    if car_is_a else point.getPositionWorldOnB()
                )
                relative_point = world_point - car.chassis_node.getPos(render)
                if outward.dot(relative_point) < 0:
                    outward = -outward
                angular_velocity = car.chassis_body.getAngularVelocity().cross(relative_point)
                other_velocity = other.getLinearVelocity()
                relative_velocity = incoming_velocity + angular_velocity - other_velocity
                closing_speed = max(0, relative_velocity.dot(outward))
                impact = max(
                    closing_speed,
                    point.getAppliedImpulse() / car.chassis_body.getMass(),
                )
                impacts.append((impact, world_point, outward))
        if (
            impacts
            and state.crash_cooldown == 0
            and state.damage_arm_timer <= 0
            and grace <= 0
        ):

            impact, world_point, outward = max(impacts, key=lambda item: item[0])
            if (
                impact > config.crash_speed_threshold
                and incoming_velocity.length() * 3.6
                >= config.damage_speed_threshold_kmh
            ):
                severity = max(0.2, min(1, (impact - config.crash_speed_threshold) / 12))
                state.damage = min(
                    100,
                    state.damage + max(2, min(18, int((impact - config.crash_speed_threshold) * 1.5))),
                )
                car.damage = state.damage
                state.crash_cooldown = config.crash_cooldown
                state.collision_slowdown = max(state.collision_slowdown, severity)
                if is_player_car:
                    self.damage_text.text = f'Sérülés: {state.damage}%'
                local_contact = car.chassis_node.getRelativePoint(render, world_point)
                local_outward = car.chassis_node.getRelativeVector(render, outward)
                car.dent_body(Vec3(local_contact), severity, Vec3(local_outward))
                nearest_wheel = min(
                    car.suspension_visuals,
                    key=lambda parts: (
                            (parts['wheel_x'] - local_contact.x) ** 2
                            + (parts['wheel_z'] - local_contact.z) ** 2
                    ),
                )
                if (
                    severity >= config.suspension_impact_threshold
                    and state.damage >= config.suspension_damage_threshold
                ):
                    car.collapse_wheel_suspension(nearest_wheel)

                if state.damage >= 100:
                    car.broken = True
                    if is_player_car:
                        self.broken = True
                        self.crash_text.enabled = True
                    car.car_body.color = rgb32(35, 55, 90)
                    car.chassis_body.applyCentralImpulse(PandaVec3(0, 2, 0))

        state.was_chassis_contacting = is_contacting

    def update(self):
        dt = min(time.dt, 1 / 30)
        self.hold_car_before_start()
        self.collision_slowdown = max(0, self.collision_slowdown - dt * 0.25)
        self.damage_arm_timer = max(0, self.damage_arm_timer - dt)
        self.wrap_grace_timer = max(0, self.wrap_grace_timer - dt)
        speed_kmh = self.car.vehicle.getCurrentSpeedKmHour()
        accelerating = held_keys['up arrow'] or held_keys['w']
        reversing = held_keys['down arrow'] or held_keys['s']
        steering = int(bool(held_keys['right arrow'] or held_keys['d'])) - int(
            bool(held_keys['left arrow'] or held_keys['a'])
        )

        engine_force = 0
        brake_force = PARKING_BRAKE_FORCE if not self.started and not self.flight_active else 8
        if self.started and not self.broken:
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
        if self.broken:
            steering_angle = 0
            brake_force = BRAKE_FORCE
        engine_force = int(engine_force * (1 - 0.65 * self.collision_slowdown))
        if self.flight_active and not self.broken:
            brake_force = 0
            self.car.chassis_body.applyCentralForce(
                PandaVec3(0, self.car.chassis_body.getMass() * FLIGHT_ACCELERATION, 0)
            )
            local_torque = self.car.chassis_node.getQuat(render).xform(PandaVec3(*FLIGHT_TORQUE))
            self.car.chassis_body.applyTorque(local_torque)

        for wheel_index in range(4):
            self.car.vehicle.setBrake(brake_force, wheel_index)
            if wheel_index < 2:
                self.car.vehicle.setSteeringValue(steering_angle, wheel_index)
            else:
                self.car.vehicle.applyEngineForce(engine_force, wheel_index)

        if steering and abs(speed_kmh) > 2 and self.started and not self.broken:
            travel_direction = 1 if speed_kmh > 0 else -1
            speed_factor = min(abs(speed_kmh) / 20, 1)
            self.car.chassis_body.applyTorque(
                PandaVec3(0, steering * STEERING_ASSIST_TORQUE * speed_factor * travel_direction, 0)
            )

        self.wrap_car_if_needed()
        incoming_velocities = [
            PandaVec3(vehicle.chassis_body.getLinearVelocity())
            for vehicle in self.vehicles
        ]
        self.physics_world.doPhysics(dt, 8, 1 / 120)
        for vehicle, incoming_velocity in zip(self.vehicles, incoming_velocities):
            vehicle.update_suspension_visuals(dt)
            vehicle.update_shadow()
            self.update_crash_state(dt, incoming_velocity, vehicle)
            vehicle.update_bodywork(dt)
            vehicle.update_terrain_particles(
                dt,
                vehicle.vehicle.getCurrentSpeedKmHour(),
            )
        self.update_intro_landing(dt)
        self.hold_car_before_start()

        speed_kmh = self.car.vehicle.getCurrentSpeedKmHour()
        self.speed_text.text = f'Sebesség: {int(abs(speed_kmh))} km/h'

        self.update_camera(dt)

    def update_camera(self, dt):
        position = self.car.chassis_node.getPos(render)
        if (
            not self.broken
            and not self.started
            and not self.flight_active
            and not self.intro_landed
        ):
            return
        orbit = self.broken or (
            self.intro_landed and not self.started and not self.flight_active
        )
        if orbit:
            if not self.orbit_active:
                offset = camera.position - Vec3(position)
                self.orbit_angle = atan2(offset.x, -offset.z)
                self.orbit_radius = max(1.0, Vec3(offset.x, 0, offset.z).length())
                self.orbit_height = camera.y
                self.orbit_pitch = camera.rotation_x
            self.orbit_active = True
            self.orbit_angle = (
                self.orbit_angle + radians(CAMERA_ORBIT_SPEED) * dt
            ) % radians(360)
            camera.position = Vec3(
                position.x + sin(self.orbit_angle) * self.orbit_radius,
                self.orbit_height,
                position.z - cos(self.orbit_angle) * self.orbit_radius,
            )
            camera.rotation = Vec3(
                self.orbit_pitch,
                -degrees(self.orbit_angle),
                0,
            )
            return

        self.orbit_active = False
        forward_vector = self.car.chassis_node.getQuat(render).xform(PandaVec3(0, 0, 1))
        forward = Vec3(forward_vector.x, 0, forward_vector.z)
        if forward.length():
            forward = forward.normalized()
        camera_target = Vec3(
            position.x - forward.x * CAMERA_DISTANCE,
            position.y + CAMERA_HEIGHT,
            position.z - forward.z * CAMERA_DISTANCE-5,
        )
        follow_amount = 1 - exp(-CAMERA_FOLLOW_SPEED * dt)
        turn_amount = 1 - exp(-CAMERA_TURN_FOLLOW_SPEED * dt)
        camera.position += (camera_target - camera.position) * follow_amount
        camera_heading = degrees(atan2(forward.x, forward.z))
        camera.rotation_x += (15 - camera.rotation_x) * follow_amount
        camera.rotation_y = smooth_angle(camera.rotation_y, camera_heading, turn_amount)
        camera.rotation_z += (0 - camera.rotation_z) * follow_amount

    def update_intro_landing(self, dt):
        if self.intro_landed or self.started or self.flight_active or self.broken:
            return

        grounded_wheels = sum(
            wheel.getRaycastInfo().isInContact()
            for wheel in self.car.vehicle_wheels
        )
        linear_speed = self.car.chassis_body.getLinearVelocity().length()
        angular_speed = self.car.chassis_body.getAngularVelocity().length()
        if grounded_wheels >= 2 and linear_speed < 0.6 and angular_speed < 0.5:
            self.intro_settled_time += dt
        else:
            self.intro_settled_time = 0

        if self.intro_settled_time >= 0.35:
            self.intro_landed = True
