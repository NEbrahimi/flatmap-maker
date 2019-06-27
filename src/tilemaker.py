#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================

import io
import math
import os
import shutil
import subprocess
import tempfile

#===============================================================================

import fitz
import mercantile as mt
import numpy as np
from PIL import Image

#===============================================================================

MAX_ZOOM  = 10
TILE_SIZE = (256, 256)
WHITE     = (255, 255, 255)
from mbtiles import MBTiles, ExtractionError

#===============================================================================


#===============================================================================

# Based on https://stackoverflow.com/a/54148416/2159023

def make_transparent(img, colour=WHITE):
    x = np.asarray(img).copy()
    if colour == WHITE:
        x[:, :, 3] = (255 * (x[:, :, :3] != 255).any(axis=2)).astype(np.uint8)
    else:
        x[:, :, 3] = (255*(x[:,:,0:3] != tuple(colour)[0:3]).any(axis=2)).astype(np.uint8)
    return Image.fromarray(x)

#===============================================================================

def not_transparent(img):
    x = np.asarray(img)
    return np.any(x[:,:,3])

#===============================================================================

class Affine(object):
    def __init__(self, scale, translateA, translateB):
        self._matrix = np.array([[ scale[0], 0, -scale[0]*translateA[0] + translateB[0] ],
                                 [ 0, scale[1], -scale[1]*translateA[1] + translateB[1] ],
                                 [ 0,        0,                                       1 ]])

    def transform(self, x, y):
        return self._matrix.dot([x, y, 1])[:2]

#===============================================================================

def check_image_size(dimension, max_dim, lower, upper, bounds, scale):
    if dimension < max_dim:
        if lower < bounds[0]:
            if upper < bounds[1]:
                return max_dim - dimension
            else:
                return int(math.floor(0.5 - lower*scale))
    else:
        assert(dimension == max_dim)
    return 0

#===============================================================================

class PageTiler(object):
    def __init__(self, pdf_page, image_rect):
        self._pdf_page = pdf_page
        self._page_rect = pdf_page.rect
        sx = self._page_rect.width/image_rect.width
        sy = self._page_rect.height/image_rect.height
        self._tile_to_image = Affine((sx, sy), (image_rect.x0, image_rect.y0), (0, 0))

    def tile_as_png(self, tile_x, tile_y):
        (x0, y0) = self._tile_to_image.transform(TILE_SIZE[0]*tile_x,
                                                 TILE_SIZE[1]*tile_y)
        (x1, y1) = self._tile_to_image.transform(TILE_SIZE[0]*(tile_x + 1),
                                                 TILE_SIZE[1]*(tile_y + 1))
        scaling = ((TILE_SIZE[0] - 1)/(x1 - x0),   # Fitz includes RH edge pixel
                   (TILE_SIZE[1] - 1)/(y1 - y0))   # so scale to 1px smaller...
        pixmap = self._pdf_page.getPixmap(clip=fitz.Rect(x0, y0, x1, y1),
                                          matrix=fitz.Matrix(*scaling),
                                          alpha=True)

        png_data = io.BytesIO(pixmap.getImageData('png'))
        image = Image.open(png_data)

        x_start = check_image_size(image.width, TILE_SIZE[0], x0, x1, (0, self._page_rect.x1), scaling[0])
        y_start = check_image_size(image.height, TILE_SIZE[1], y0, y1, (0, self._page_rect.y1), scaling[1])
        if image.size == tuple(TILE_SIZE):
            return make_transparent(image)
        else:
            # Pad out partial tiles
            tile = Image.new('RGBA', TILE_SIZE, (255, 255, 255, 0))
            tile.paste(image, (x_start, y_start))
            return make_transparent(tile)

#===============================================================================

class TileMaker(object):
    def __init__(self, extent, map_dir, max_zoom=MAX_ZOOM):
        self._map_dir = map_dir
        self._max_zoom = max_zoom

        # Get whole tiles that span the image's extent
        self._tiles = list(mt.tiles(*extent, max_zoom))
        tile_0 = self._tiles[0]
        tile_N = self._tiles[-1]
        self._tile_start_coords = (tile_0.x, tile_0.y)
        self._tile_end_coords = (tile_N.x, tile_N.y)

        # Tiled area in world coordinates (metres)
        bounds_0 = mt.xy_bounds(tile_0)
        bounds_N = mt.xy_bounds(tile_N)
        tile_world = fitz.Rect(bounds_0.left, bounds_0.top, bounds_N.right, bounds_N.bottom)

        # Tiled area in tile pixel coordinates
        tile_extent = fitz.Rect(0, 0, TILE_SIZE[0]*(tile_N.x-tile_0.x+1), TILE_SIZE[1]*(tile_N.y-tile_0.y+1))

        # Affine transform from world to tile pixel coordinates
        sx = tile_extent.width/tile_world.width
        sy = tile_extent.height/tile_world.height
        world_to_tile = Affine((sx, -sy), (tile_world.x0, tile_world.y0), (0, 0))

        # Extent in world coordinates (metres)
        sw = mt.xy(*extent[:2])
        ne = mt.xy(*extent[2:])

        # Converted to tile pixel coordinates
        self._image_rect = fitz.Rect(world_to_tile.transform(sw[0], ne[1]),
                                     world_to_tile.transform(ne[0], sw[1]))

    def make_tiles(self, pdf_page, layer):
        page_tiler = PageTiler(pdf_page, self._image_rect)
        mbtiles = MBTiles(os.path.join(self._map_dir, '{}.mbtiles'.format(layer)), True)

        ## TODO: mbtiles.save_metadata(key=val, key=val)

        count = 0
        zoom = self._max_zoom
        print('Tiling zoom level {} for {}'.format(zoom, layer))
        for tile in self._tiles:
            png = page_tiler.tile_as_png(tile.x - self._tile_start_coords[0],
                                         tile.y - self._tile_start_coords[1])
            if not_transparent(png):
                if (count % 100) == 0:
                    print("  Tile number: {} at ({}, {})".format(count, tile.x, tile.y))
                mbtiles.save_tile(zoom, tile.x, tile.y, png)
                count += 1
        print("  {} tiles".format(count))

        self.make_overview_tiles(mbtiles, layer, zoom, self._tile_start_coords, self._tile_end_coords)
        mbtiles.close() #True)

    def make_overview_tiles(self, mbtiles, layer, zoom, start_coords, end_coords):
        if zoom > 0:
            zoom -= 1
            count = 0
            print('Tiling zoom level {} for {}'.format(zoom, layer))
            HALF_SIZE = (TILE_SIZE[0]//2, TILE_SIZE[1]//2)
            half_start = (start_coords[0]//2, start_coords[1]//2)
            half_end = (end_coords[0]//2, end_coords[1]//2)
            for x in range(half_start[0], half_end[0] + 1):
                for y in range(half_start[1], half_end[1] + 1):
                    overview_tile = Image.new('RGBA', TILE_SIZE, (255, 255, 255, 0))
                    for i in range(2):
                        for j in range(2):
                            try:
                                tile = mbtiles.get_tile(zoom+1, 2*x+i, 2*y+j)
                                half_tile = tile.resize((HALF_SIZE[0], HALF_SIZE[1]), Image.LANCZOS)
                                overview_tile.paste(half_tile, (i*HALF_SIZE[0], j*HALF_SIZE[1]))
                            except ExtractionError:
                                pass
                    if not_transparent(overview_tile):
                        if (count % 100) == 0:
                            print("  Tile number: {} at ({}, {})".format(count, x, y))
                        mbtiles.save_tile(zoom, x, y, overview_tile)
                        count += 1
            print("  {} tiles".format(count))
            self.make_overview_tiles(mbtiles, layer, zoom, half_start, half_end)

#===============================================================================

def make_image(pdf_file, image_file):
#====================================
    print('Generating {}...'.format(image_file))
    subprocess.run(['convert',
        '-density', '72',
        '-transparent', 'white',
        pdf_file, image_file])


def make_background_images(layer_ids, map_dir, pdf_file):
#========================================================
    map_image_dir = os.path.join(map_dir, 'images')
    if not os.path.exists(map_image_dir):
        os.makedirs(map_image_dir)

    work_dir = tempfile.mkdtemp()

    subprocess.run(['qpdf', '--split-pages', pdf_file, os.path.join(work_dir, 'slide%d.pdf')])

    make_image(os.path.join(work_dir, 'slide01.pdf'),
               os.path.join(map_image_dir, 'background.png'))
    for n, layer_id in enumerate(layer_ids):
        make_image(os.path.join(work_dir, 'slide{:02d}.pdf'.format(n+2)),
                   os.path.join(map_image_dir, '{}.png'.format(layer_id)))

    shutil.rmtree(work_dir)

#===============================================================================

if __name__ == '__main__':
    import sys

    map_extent = [-56.5938090006128, -85.53899259200053,
                   56.5938090006128,  85.53899259200054]
    tm = TileMaker(map_extent, '../maps/demo', int(sys.argv[1]))

    pdf = fitz.open('../map_sources/body_demo.pdf')
    pages = list(pdf)

    tm.make_tiles(pages[0], 'background')
    #for n, page in enumerate(pdf):
    #    print(n)

#===============================================================================