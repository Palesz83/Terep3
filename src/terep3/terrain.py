"""Terrain generation, rendering, collision, and surface queries."""
from PIL import Image, ImageFilter
from random import Random
from panda3d.bullet import BulletRigidBodyNode, BulletTriangleMesh, BulletTriangleMeshShape, BulletWorld
from panda3d.core import Vec3 as PandaVec3
from ursina import *
from ursina.color import rgb32, white, rgba32

from .config import *


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


def interpolated_cell_value(values, row, column, u, v):
    top_left = values[row][column]
    top_right = values[row][column + 1]
    bottom_left = values[row + 1][column]
    bottom_right = values[row + 1][column + 1]
    if u + v <= 1:
        return top_left * (1 - u - v) + top_right * u + bottom_left * v
    return top_right * (1 - v) + bottom_left * (1 - u) + bottom_right * (u + v - 1)


class Terrain:
    def __init__(self, physics_world):
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
        self.map_image = map_image
        self.heightmap = heightmap
        self.terrain_vertices = terrain_vertices
        self.terrain_triangles = terrain_triangles
        self.terrain_mesh = terrain_mesh
        self.pixelated_terrain_mesh = pixelated_terrain_mesh
        self.terrain_visuals = terrain_visuals
        self.physics_world = physics_world

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
                self.physics_world.attachRigidBody(terrain_body)
                terrain_bodies.append(terrain_body)
                terrain_nodes.append(terrain_node)
        self.terrain_bodies = terrain_bodies
        self.terrain_nodes = terrain_nodes

    def height(self, x, z):
        column = min(max((x / WORLD_SIZE + 0.5) * (MAP_RESOLUTION - 1), 0), MAP_RESOLUTION - 1)
        row = min(max((0.5 - z / WORLD_SIZE) * (MAP_RESOLUTION - 1), 0), MAP_RESOLUTION - 1)
        left = min(int(column), MAP_RESOLUTION - 2)
        top = min(int(row), MAP_RESOLUTION - 2)
        x_fraction = column - left
        z_fraction = row - top
        top_height = self.heightmap[top][left] * (1 - x_fraction) + self.heightmap[top][left + 1] * x_fraction
        bottom_height = self.heightmap[top + 1][left] * (1 - x_fraction) + self.heightmap[top + 1][left + 1] * x_fraction
        return top_height * (1 - z_fraction) + bottom_height * z_fraction

    def surface_height(self, x, z):
        local_x = (x + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
        local_z = (z + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
        column = (local_x / WORLD_SIZE + 0.5) * (MAP_RESOLUTION - 1)
        row = (0.5 - local_z / WORLD_SIZE) * (MAP_RESOLUTION - 1)
        left = min(int(column), MAP_RESOLUTION - 2)
        top = min(int(row), MAP_RESOLUTION - 2)
        return interpolated_cell_value(self.heightmap, top, left, column - left, row - top)

    def particle_style(self, world_x, world_z):
        local_x = (world_x + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
        local_z = (world_z + WORLD_HALF) % WORLD_SIZE - WORLD_HALF
        column = max(0, min(MAP_RESOLUTION - 1, round((local_x / WORLD_SIZE + 0.5) * (MAP_RESOLUTION - 1))))
        row = max(0, min(MAP_RESOLUTION - 1, round((0.5 - local_z / WORLD_SIZE) * (MAP_RESOLUTION - 1))))
        red, green, blue = self.map_image.getpixel((column, row))
        is_water = blue > red * 1.3 and blue > green * 1.15
        is_brown = red > green + 8 and green > blue + 8 and blue > 15 and red < 215
        is_grass = green > red + 8 and green > blue + 6
        if is_water:
            return rgba32(85, 175, 240, 175), Vec3(0.055, 0.075, 0.055), 0.2
        if is_grass:
            return rgba32(100, 165, 75, 145), Vec3(0.055, 0.14, 0.045), 0.2
        if is_brown:
            return rgba32(166, 128, 88, 130), Vec3(0.13, 0.10, 0.13), 0.2
        color = rgba32(min(255, int(red * 0.75 + 64)), min(255, int(green * 0.75 + 64)), min(255, int(blue * 0.75 + 64)), 125)
        return color, Vec3(0.10, 0.08, 0.10), 0.2
