"""Shared game configuration."""
from dataclasses import dataclass, field
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


@dataclass(frozen=True)
class DamageConfig:
    body_damage_threshold: float = 30
    suspension_damage_threshold: float = 50
    suspension_impact_threshold: float = 0.75
    crash_speed_threshold: float = 7.0
    damage_speed_threshold_kmh: float = 50
    crash_cooldown: float = 0.35
    body_deformation_strength: float = 0.5
    bumper_mount_failure_threshold: float = 0.3
    max_body_roll: float = 12.0


DAMAGE_CONFIG = DamageConfig()


@dataclass(frozen=True)
class GameConfig:
    map_image: Path = field(default_factory=lambda: ASSET_ROOT / "COL-CLASSIC.png")
    map_resolution: int = 128
    world_size: int = 300
    tile_seam_blend_width: int = 8
    subpixel_divisions: int = 2
    subpixel_color_variation: int = 5
    max_mountain_height: int = 7
    height_smoothing_radius: int = 1
    max_forward_speed_kmh: int = 200
    max_reverse_speed_kmh: int = 200
    engine_force: int = 2200
    reverse_force: int = 1000
    brake_force: int = 20
    parking_brake_force: int = 1000
    steering_angle: int = 15
    reverse_steering_scale: int = 15
    steering_assist_torque: int = 1800
    flight_acceleration: int = 16
    flight_torque: tuple[int, int, int] = (3000, 2600, 3400)
    camera_distance: int = 15
    camera_height: int = 8
    camera_follow_speed: int = 2
    camera_turn_follow_speed: int = 3
    camera_orbit_speed: int = 12
    damage_arm_delay: float = 2.0
    wheel_impact_distance_threshold: float = 0.06
    wheel_impact_speed_threshold: float = 2.0
    wheel_dent_severity_threshold: float = 0.20
    suspension_visual_smoothing: int = 24
    dust_particle_count: int = 96


CONFIG = GameConfig()
MAP_IMAGE = CONFIG.map_image
MAP_RESOLUTION = CONFIG.map_resolution
WORLD_SIZE = CONFIG.world_size
WORLD_HALF = WORLD_SIZE / 2
TILE_SEAM_BLEND_WIDTH = CONFIG.tile_seam_blend_width
SUBPIXEL_DIVISIONS = CONFIG.subpixel_divisions
SUBPIXEL_COLOR_VARIATION = CONFIG.subpixel_color_variation
MAX_MOUNTAIN_HEIGHT = CONFIG.max_mountain_height
HEIGHT_SMOOTHING_RADIUS = CONFIG.height_smoothing_radius
MAX_FORWARD_SPEED_KMH = CONFIG.max_forward_speed_kmh
MAX_REVERSE_SPEED_KMH = CONFIG.max_reverse_speed_kmh
ENGINE_FORCE = CONFIG.engine_force
REVERSE_FORCE = CONFIG.reverse_force
BRAKE_FORCE = CONFIG.brake_force
PARKING_BRAKE_FORCE = CONFIG.parking_brake_force
STEERING_ANGLE = CONFIG.steering_angle
REVERSE_STEERING_SCALE = CONFIG.reverse_steering_scale
STEERING_ASSIST_TORQUE = CONFIG.steering_assist_torque
FLIGHT_ACCELERATION = CONFIG.flight_acceleration
FLIGHT_TORQUE = CONFIG.flight_torque

CAMERA_DISTANCE = CONFIG.camera_distance
CAMERA_HEIGHT = CONFIG.camera_height
CAMERA_FOLLOW_SPEED = CONFIG.camera_follow_speed
CAMERA_TURN_FOLLOW_SPEED = CONFIG.camera_turn_follow_speed
CAMERA_ORBIT_SPEED = CONFIG.camera_orbit_speed

CRASH_SPEED_THRESHOLD = DAMAGE_CONFIG.crash_speed_threshold
DAMAGE_ARM_DELAY = CONFIG.damage_arm_delay
WHEEL_IMPACT_DISTANCE_THRESHOLD = CONFIG.wheel_impact_distance_threshold
WHEEL_IMPACT_SPEED_THRESHOLD = CONFIG.wheel_impact_speed_threshold
WHEEL_DENT_SEVERITY_THRESHOLD = CONFIG.wheel_dent_severity_threshold
SUSPENSION_COLLAPSE_SEVERITY_THRESHOLD = DAMAGE_CONFIG.suspension_impact_threshold
SUSPENSION_VISUAL_SMOOTHING = CONFIG.suspension_visual_smoothing
DUST_PARTICLE_COUNT = CONFIG.dust_particle_count

__all__ = [name for name in globals() if name.isupper()] + ["GameConfig", "DamageConfig"]
