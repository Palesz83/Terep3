"""Persistent, local-space visual damage; the Bullet chassis stays rigid."""
from math import sin

from panda3d.core import Vec3

from .config import DAMAGE_CONFIG


class BodyDeformation:
    def __init__(self, config=DAMAGE_CONFIG):
        self.config = config
        self.reset()

    def reset(self):
        self.zones = dict.fromkeys(('front', 'rear', 'left', 'right', 'roof'), 0.0)
        self.hits = dict.fromkeys(self.zones, 0)
        self.centers = {zone: Vec3(0, 0, 0) for zone in self.zones}

    @staticmethod
    def impact_zone(point, outward=None):
        if point.y > 0.45 and (outward is None or outward.y > 0.5):
            return 'roof'
        if outward is not None:
            if abs(outward.z) > 0.5 and abs(outward.z) >= abs(outward.x):
                return 'front' if outward.z > 0 else 'rear'
            if abs(outward.x) > 0.5 and abs(outward.x) > abs(outward.z):
                return 'right' if outward.x > 0 else 'left'
        if abs(point.z) / 1.3 >= abs(point.x) / 0.85:
            return 'front' if point.z >= 0 else 'rear'
        return 'right' if point.x >= 0 else 'left'

    def impact(self, point, severity, damage, outward=None):
        zone = self.impact_zone(point, outward)
        if damage < self.config.body_damage_threshold or severity <= 0:
            return zone
        old = self.zones[zone]
        added = min(1.0, severity) * 0.28 * self.config.body_deformation_strength
        self.zones[zone] = min(1.0, old + added)
        # A weighted center keeps earlier damage instead of forgetting old hits.
        self.centers[zone] = (self.centers[zone] * old + point * added) / (old + added)
        self.hits[zone] += 1
        return zone

    def deform(self, point):
        original = Vec3(point)
        result = Vec3(point)
        for zone, amount in self.zones.items():
            if amount == 0:
                continue
            center = self.centers[zone]
            if zone in ('front', 'rear'):
                sign = 1 if zone == 'front' else -1
                weight = max(0.0, min(1.0, (sign * original.z - 0.05) / 1.29))
                lateral = max(0.35, 1 - abs(original.x - center.x) / 1.7)
                crush = amount * weight * lateral
                result.z -= sign * 0.95 * crush
                result.y -= max(0, original.y + 0.18) * 0.65 * crush
                result.y += sin(original.z * 23 + original.x * 7) * 0.12 * crush
                result.x += sin(original.z * 17) * 0.09 * crush
            elif zone in ('left', 'right'):
                sign = 1 if zone == 'right' else -1
                weight = max(0.0, min(1.0, (sign * original.x + 0.12) / 0.92))
                longitudinal = max(0.0, 1 - abs(original.z - center.z) / 1.45)
                crush = amount * weight * longitudinal
                result.x -= sign * 0.55 * crush
                result.y -= max(0, original.y + 0.18) * 0.35 * crush
                result.z += sin(original.z * 19 + original.y * 8) * 0.09 * crush
            else:
                weight = max(0, min(1, (original.y - 0.1) / 0.8))
                result.y -= 0.65 * amount * weight
                result.x += sin(original.z * 11) * 0.08 * amount * weight
        return result

    @property
    def roll(self):
        return (self.zones['right'] - self.zones['left']) * self.config.max_body_roll


class BumperDeformation:
    def __init__(self, forward_sign, config=DAMAGE_CONFIG):
        self.forward_sign = forward_sign
        self.config = config
        self.reset()

    def reset(self):
        self.left = 0.0
        self.right = 0.0
        self.broken_mount = 0

    def impact(self, point, severity):
        strength = min(1.0, max(0, severity)) * 0.3
        right_weight = max(0, min(1, (point.x + 0.8) / 1.6))
        self.left = min(1.0, self.left + strength * (1 - 0.8 * right_weight))
        self.right = min(1.0, self.right + strength * (0.2 + 0.8 * right_weight))
        if not self.broken_mount:
            if max(self.left, self.right) >= self.config.bumper_mount_failure_threshold:
                self.broken_mount = -1 if self.left >= self.right else 1

    def deform(self, point, time=0.0):
        blend = max(0, min(1, (point.x + 0.8) / 1.6))
        stress = self.left * (1 - blend) + self.right * blend
        center_bend = 4 * blend * (1 - blend) * max(self.left, self.right)
        result = Vec3(
            point.x,
            point.y - 0.12 * stress,
            point.z - self.forward_sign * (0.38 * stress + 0.15 * center_bend),
        )
        if self.broken_mount:
            # One mount stays attached; only the loose end drops and swings.
            loose_weight = blend if self.broken_mount > 0 else 1 - blend
            result.y -= loose_weight * (0.7 + 0.25 * stress + 0.06 * sin(time * 7))
            result.z += self.forward_sign * loose_weight * (0.24 + 0.05 * sin(time * 5))
            result.x -= self.broken_mount * 0.15 * loose_weight
        return result
