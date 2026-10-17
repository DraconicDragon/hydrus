import bisect
import threading
import traceback
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import math

import numpy as np
from qtpy import QtCore as QC
from qtpy import QtWidgets as QW

from hydrus.client import ClientApplicationCommand as CAC

class ScrollDirection( Enum ):
    VERTICAL = 0
    HORIZONTAL = 1
    
@dataclass( frozen = True )
class LayoutParams:
    viewport_width: int
    viewport_height: int
    thumb_width: int
    thumb_height: int
    thumb_content_width: int
    thumb_content_height: int
    thumb_margin_vertical: int
    thumb_margin_horizontal: int
    scene_margin_vertical: int
    scene_margin_horizontal: int
    scroll_direction: ScrollDirection
    content_alignment: QC.Qt.AlignmentFlag
    zoom: float
    

class ThumbnailLayout( ABC ):
    
    @abstractmethod
    def ArrangeThumbnails( self, thumbnails, params: LayoutParams ) -> QC.QRectF:
        """
        Sets positions and sizes for the given thumbnails.
        It is assumed that the thumbnail list passed here contains ALL thumbnails of the page (so index 0 is at row 0 and col 0, etc.).
        This is not ideal since we have to rearrange all thumbnails every time the layout changes,
        but in more complex layouts the positions of later thumbnails will depend on the positions/sizes of earlier ones,
        so in general we cannot easily recalculate starting from the Nth thumbnail only (but some clever optimizations might be possible).
        The layout parameters and calculation results are cached.
        All other functions of this class rely on the calculations done here, so this should be called first,
        and every time the order or number of thumbnails changes.
        This is because in complex layouts the other functions might need data calculated while
        arranging the thumbnails. If this function is not called first, the others can/will only return dummy values.
        For complex layouts with many thumbnails, this function is a performance bottleneck,
        take care to make it as fast as possible!
        Returns the new scene rect.
        """
        raise NotImplementedError()
        
    
    @abstractmethod
    def MoveFromIndex( self, original_index: int, direction: int ) -> int:
        """
        Returns the new media index after moving left, right, up, or down, starting from the original index.
        Does NOT clamp the result index to the range of valid media indices, that is the caller's responsibility!
        """
        raise NotImplementedError()
        
    
    @abstractmethod
    def JumpPage( self, scene_rect: QC.QRectF, media_index: int, direction: int, percent_visible: float ) -> int:
        """
        Returns the new media index if we jump one page worth,
        if starting from the given media and visible scene rect, in the given direction (-1 = backward, 1 = forward).
        Does NOT clamp the result index to the range of valid media indices, that is the caller's responsibility!
        """
        raise NotImplementedError()
        
    
    @abstractmethod
    def ThumbnailSpanDimensions( self, thumbnail ) -> tuple[int, int]:
        """
        Returns the size of the rect "belonging" to this thumbnail,
        including any thumbnail margins (so possibly larger than the bounding rect of the thumb).
        If passed None, it should return a "generic"/"average"/"fallback" size.
        """
        raise NotImplementedError()
        
    

class RegularGridLayout( ThumbnailLayout ):
    
    def __init__( self ):
        
        self._params = None
        
        self._viewport_width = 0
        self._viewport_height = 0
        self._col_width = 0
        self._row_height = 0
        self._thumbs_in_a_row = 1
        self._thumbs_in_a_col = 1
        self._extra_padding_on_top = 0
        self._extra_padding_on_left = 0
        
    
    def ArrangeThumbnails( self, thumbnails, params: LayoutParams ) -> QC.QRectF:
        
        self._params = params
        
        count = len( thumbnails )
        
        
        tw = round( params.thumb_width * params.zoom )
        th = round( params.thumb_height * params.zoom )
        self._viewport_width = params.viewport_width - 2 * params.scene_margin_horizontal
        self._viewport_height = params.viewport_height - 2 * params.scene_margin_vertical
        self._col_width = tw + 2 * params.thumb_margin_horizontal
        self._row_height = th + 2 * params.thumb_margin_vertical
        self._thumbs_in_a_row = max( 1, self._viewport_width // self._col_width )
        self._thumbs_in_a_col = max( 1, self._viewport_height // self._row_height )
        
        leftover_space_horizontal = self._viewport_width - self._thumbs_in_a_row * self._col_width
        leftover_space_vertical = self._viewport_height - self._thumbs_in_a_col * self._row_height
        self._extra_padding_on_left = 0
        self._extra_padding_on_top = 0
        
        if params.scroll_direction == ScrollDirection.VERTICAL:
            
            if params.content_alignment == QC.Qt.AlignmentFlag.AlignRight:
                
                self._extra_padding_on_left = leftover_space_horizontal
                
            elif params.content_alignment == QC.Qt.AlignmentFlag.AlignHCenter:
                
                self._extra_padding_on_left = leftover_space_horizontal / 2
                
            
        else:
        
            if params.content_alignment == QC.Qt.AlignmentFlag.AlignBottom:
                
                self._extra_padding_on_top = leftover_space_vertical
                
            elif params.content_alignment == QC.Qt.AlignmentFlag.AlignVCenter:
                
                self._extra_padding_on_top = leftover_space_vertical / 2
                
        
        row = 0
        col = 0
        i = 0
        for thumb in thumbnails:
            
            thumb._index = i
            thumb.width = tw
            thumb.height = th
            thumb.setPos( self._extra_padding_on_left + params.scene_margin_horizontal + col * self._col_width + params.thumb_margin_horizontal, self._extra_padding_on_top + params.scene_margin_vertical + row * self._row_height + params.thumb_margin_vertical )
            thumb.setVisible( True )
            
            if params.scroll_direction == ScrollDirection.VERTICAL:
                col += 1
                if col == self._thumbs_in_a_row:
                    col = 0
                    row += 1
            else:
                row += 1
                if row == self._thumbs_in_a_col:
                    row = 0
                    col += 1
                
            i += 1
            
        
        if params.scroll_direction == ScrollDirection.VERTICAL:
            
            return QC.QRectF( 0, 0, self._extra_padding_on_left + 2 * params.scene_margin_horizontal + self._thumbs_in_a_row * self._col_width, self._extra_padding_on_top + 2 * params.scene_margin_vertical + math.ceil( count / self._thumbs_in_a_row ) * self._row_height )
            
        else:
            
            return QC.QRectF( 0, 0, self._extra_padding_on_left + 2 * params.scene_margin_horizontal + math.ceil( count / self._thumbs_in_a_col ) * self._col_width, self._extra_padding_on_top + 2 * params.scene_margin_vertical + self._thumbs_in_a_col * self._row_height )
            
        
    def MoveFromIndex( self, original_index: int, direction: int ) -> int:
        
        rows_moved = 0
        cols_moved = 0
        
        if direction == CAC.MOVE_UP:
            
            rows_moved = -1
            
        elif direction == CAC.MOVE_DOWN:
            
            rows_moved = 1
            
        elif direction == CAC.MOVE_LEFT:
            
            cols_moved = -1
            
        elif direction == CAC.MOVE_RIGHT:
            
            cols_moved = 1
            
        else:
            
            raise NotImplementedError()
            
        if self._params is None or self._params.scroll_direction == ScrollDirection.VERTICAL:
            
            return original_index + rows_moved * self._thumbs_in_a_row + cols_moved
            
        else:
            
            return original_index + rows_moved + cols_moved * self._thumbs_in_a_col
            
        
    
    def JumpPage( self, scene_rect: QC.QRectF, media_index: int, direction: int, percent_visible: float ) -> int:
        
        return media_index + direction * self._thumbs_in_a_col * self._thumbs_in_a_row
        
    
    def ThumbnailSpanDimensions( self, thumbnail ) -> tuple[int, int]:
        
        # This is a regular grid so the result doesn't depend on the passed in thumbnail
        
        return self._col_width, self._row_height
        
    

# TODO: implement horizontal scrolling version (i.e. support scroll_direction HORIZONTAL, like in RegularGridLayout)
class MasonryLayout(ThumbnailLayout): # also known as Waterfall layout
    
    class VariableDimension(Enum):
        WIDTH = 0
        HEIGHT = 1
        
    
    def __init__( self, variable_dimension: VariableDimension ):
        
        self._variable_dimension = variable_dimension
        
        self._params = None
        
        self._viewport_width = 0
        self._viewport_height = 0
        self._col_width = 0
        self._row_height = 0
        self._thumbs_in_a_row = 1
        self._thumbs_in_a_col = 1
        self._col_heights = np.array( [], dtype=np.int64 )
        self._col_indices = np.array( [], dtype=np.int32 ) # _col_indices and _thumb_heights are only needed for the jump page implementation, would be nice to remove somehow
        self._thumb_heights = np.array( [], dtype=np.int32 )
        self._extra_padding_on_left = 0
        
    
    def ArrangeThumbnails( self, thumbnails, params: LayoutParams ) -> QC.QRectF:
        
        self._params = params
        
        count = len( thumbnails )
        
        
        tw = round( params.thumb_width * params.zoom )
        th = round( params.thumb_height * params.zoom )
        tcw = params.thumb_content_width * params.zoom
        tch = params.thumb_content_height * params.zoom
        self._viewport_width = params.viewport_width - 2 * params.scene_margin_horizontal
        self._viewport_height = params.viewport_height - 2 * params.scene_margin_vertical
        self._col_width = tw + 2 * params.thumb_margin_horizontal
        self._row_height = th  + 2 * params.thumb_margin_vertical
        self._thumbs_in_a_row = int( max( 1, self._viewport_width // self._col_width ) )
        self._thumbs_in_a_col = int( max( 1, self._viewport_height // self._row_height ))
        self._col_heights = np.full( self._thumbs_in_a_row, params.scene_margin_vertical, dtype=np.int64 )
        self._col_indices = np.full( count, -1, dtype=np.int32 )
        self._thumb_heights = np.full( count, 0, dtype=np.int32 )
        
        if self._variable_dimension == MasonryLayout.VariableDimension.HEIGHT:
        
            leftover_space_horizontal = self._viewport_width - self._thumbs_in_a_row * self._col_width
            if count < self._thumbs_in_a_row: # handle the case where the thumbs don't even fill a single row

                leftover_space_horizontal += self._col_width * ( self._thumbs_in_a_row - count )
            self._extra_padding_on_left = 0
            
            if params.content_alignment == QC.Qt.AlignmentFlag.AlignRight:
                
                self._extra_padding_on_left = leftover_space_horizontal
                
            elif params.content_alignment == QC.Qt.AlignmentFlag.AlignHCenter:
                
                self._extra_padding_on_left = leftover_space_horizontal / 2
            
        
        thumb_padding_hor = tw - tcw
        thumb_padding_ver = th - tch
        
        row = 0
        col = 0
        i = 0
        
        if self._variable_dimension == MasonryLayout.VariableDimension.HEIGHT:
            
            for thumb in thumbnails:
                
                self._col_heights[ col ] += params.thumb_margin_vertical
                
                thumb._index = i
                thumb.width = tw
                thumb.height = round( thumb_padding_ver + thumb.res_y * tcw / thumb.res_x ) # width/height MUST be integers
                thumb.setPos( self._extra_padding_on_left + params.scene_margin_horizontal + col * self._col_width + params.thumb_margin_horizontal, self._col_heights[ col ] )
                self._col_heights[ col ] += thumb.height + params.thumb_margin_vertical
                thumb.setVisible( True )
                
                self._col_indices[ i ] = col
                self._thumb_heights[ i ] = thumb.height
                
                col += 1
                if col == self._thumbs_in_a_row:
                    col = 0
                    row += 1
                    
                i += 1
                
            
        else:
            
            # we can only align horizontally the items in a row after a row is completed,
            # since we don't know the width all the items are taking up ahead of time due to the variable width items
            def set_row_alignment( row_items, current_col_pos ):
                
                row_extra_left_padding = 0
                if params.content_alignment == QC.Qt.AlignmentFlag.AlignRight:
                    
                    row_extra_left_padding = self._viewport_width - current_col_pos
                    
                elif params.content_alignment == QC.Qt.AlignmentFlag.AlignHCenter:
                    
                    row_extra_left_padding = ( self._viewport_width - current_col_pos ) / 2
                    
                for item in row_items: item.setPos(item.pos().x() + row_extra_left_padding, item.pos().y())
                
            
            current_col_pos = 0
            max_row_width = 0
            row_items = []
            
            for thumb in thumbnails:
                
                current_col_pos += params.thumb_margin_horizontal
                thumb._index = i
                thumb.width = round( thumb_padding_hor + thumb.res_x * tch / thumb.res_y ) # width/height MUST be integers
                thumb.height = th
                
                self._col_indices[ i ] = len(row_items)
                self._thumb_heights[ i ] = th
                
                if current_col_pos + params.thumb_margin_horizontal + thumb.width > self._viewport_width:
                    
                    row += 1
                    
                    if current_col_pos > max_row_width: max_row_width = current_col_pos
                    
                    set_row_alignment( row_items, current_col_pos )
                    row_items = []
                    
                    current_col_pos = params.thumb_margin_horizontal
                    
                
                thumb.setPos( params.scene_margin_horizontal + current_col_pos, params.scene_margin_vertical + params.thumb_margin_vertical + row * self._row_height )
                row_items.append(thumb)
                thumb.setVisible( True )
                current_col_pos += params.thumb_margin_horizontal + thumb.width
                i += 1
                
            
            if row_items: set_row_alignment( row_items, current_col_pos ) # do not forget the last row!
            
        
        if self._variable_dimension == MasonryLayout.VariableDimension.HEIGHT:
            
            return QC.QRectF( 0, 0, self._extra_padding_on_left + 2 * params.scene_margin_horizontal + self._thumbs_in_a_row * self._col_width, params.scene_margin_vertical + self._col_heights.max() )
            
        else:
            
            return QC.QRectF( 0, 0, params.viewport_width, ( row + 1 ) * self._row_height + 2 * params.scene_margin_vertical )
            
        
    
    def MoveFromIndex( self, original_index: int, direction: int ) -> int:
        
        rows_moved = 0
        cols_moved = 0
        
        if direction == CAC.MOVE_UP:
            
            rows_moved = -1
            
        elif direction == CAC.MOVE_DOWN:
            
            rows_moved = 1
            
        elif direction == CAC.MOVE_LEFT:
            
            cols_moved = -1
            
        elif direction == CAC.MOVE_RIGHT:
            
            cols_moved = 1
            
        else:
            
            raise NotImplementedError()
            
        
        return original_index + rows_moved * self._thumbs_in_a_row + cols_moved
        
        
    
    def JumpPage( self, scene_rect: QC.QRectF, media_index: int, direction: int, percent_visible: float ) -> int:
        
        # Basic idea is to stay in the same column and move up/down 1 viewport height's worth
        
        idx = media_index + direction
        height_moved = 0 if direction == -1 else self._thumb_heights[ media_index ] # if moving up we start from the "top" of the current media, if moving down, we also have to jump over the height of the current media too
        
        while True:
            
            # keep stepping until we reach the thumb in the same column one row above/below us
            while 0 <= idx < len( self._col_indices ) and self._col_indices[ idx ] != self._col_indices[ media_index ]:
                
                idx += direction
                
            if direction == -1: # if we are going up, then at this point we've arrived at the top of the previous image in the same column, meaning we already moved its height (if we consider current position to be the selected image's top)
                
                height_moved += self._thumb_heights[ idx ]
                
            # if we moved enough height or reached the start/end, break
            if height_moved >= self._params.viewport_height or idx <= 0 or idx >= len(self._col_indices) - 1: break
            
            if direction == 1: # if we are moving down, then even though we've reached the next image in the same column by this point, we are at the top of that next image so we haven't moved its height down yet - so in the previous check that height should not appear and we are adding it only here after the check
                
                height_moved += self._thumb_heights[ idx ]
                
            idx += direction
            
        return idx
        
    
    def ThumbnailSpanDimensions( self, thumbnail ) -> tuple[int, int]:
        
        if self._params is None or thumbnail is None:
            
            return self._col_width, self._row_height
            
        # this requires that thumbnail borders are included in the thumbnail width/height (which is now true but should be kept in mind)
        return thumbnail.width + 2 * self._params.thumb_margin_horizontal, thumbnail.height + 2 * self._params.thumb_margin_vertical
        
    

USE_NUMBA = False

HAVE_NUMBA = False
if USE_NUMBA:
    try:
        from numba import njit
        HAVE_NUMBA = True
        print( "[MosaicLayout] Engine: NUMBA JIT (nogil, fastmath) -> ACTIVE" )
    except ImportError:
        HAVE_NUMBA = False
        print( "[MosaicLayout] WARNING: Numba requested but not found. Falling back to Pure Python." )
else:
    print( "[MosaicLayout] Engine: PURE PYTHON -> FORCED" )

if not HAVE_NUMBA:
    def njit( *args, **kwargs ):
        def decorator( func ):
            return func
        return decorator


@njit( nogil = True, fastmath = True )
def _numba_spread_pen( mx: float, mn: float, spread_free: float ) -> float:
    d = mx - mn - spread_free
    return d * d if d > 0.0 else 0.0


@njit( nogil = True, fastmath = True )
def _numba_fill_intervals(
    n: int, K: int, NB: int, BW: float, HB: int, NMAX: int, SPREAD_W: float, spread_free: float,
    tA, tLn, tS, tQ, tMx, tMn, tK, tO, tL, tR, cnt, MC,
    bUse, bQ, bS, bLn, bKey, bMx, bMn, bK, bO, bL, bR, occ
):
    for length in range( 2, n + 1 ):
        for i in range( n - length + 1 ):
            j = i + length
            iv = i * ( NMAX + 1 ) + j
            for b in range( NB ):
                bUse[ b ] = 0
            
            for k in range( i + 1, j ):
                il = i * ( NMAX + 1 ) + k
                ir = k * ( NMAX + 1 ) + j
                ml = MC[ k ] - MC[ i ]
                mr = MC[ j ] - MC[ k ]
                cnt_il = cnt[ il ]
                cnt_ir = cnt[ ir ]
                if cnt_il == 0 or cnt_ir == 0:
                    continue
                il_base = il * K
                ir_base = ir * K
                
                for a in range( cnt_il ):
                    l = il_base + a
                    tAl, tLnl, tSl, tQl, tMxl, tMnl = tA[ l ], tLn[ l ], tS[ l ], tQ[ l ], tMx[ l ], tMn[ l ]
                    
                    for c in range( cnt_ir ):
                        r = ir_base + c
                        tAr, tLnr, tSr, tQr, tMxr, tMnr = tA[ r ], tLn[ r ], tS[ r ], tQ[ r ], tMx[ r ], tMn[ r ]
                        LS = math.log( tAl + tAr )
                        
                        # Side by side cut (o=0)
                        pl = tLnl - LS
                        pr = tLnr - LS
                        Q_val = tQl + 2.0 * pl * tSl + ml * pl * pl + tQr + 2.0 * pr * tSr + mr * pr * pr
                        u = tMxl + pl; v = tMxr + pr
                        mx = u if u > v else v
                        u = tMnl + pl; v = tMnr + pr
                        mn = u if u < v else v
                        d = mx - mn - spread_free
                        pen = d * d if d > 0.0 else 0.0
                        key = Q_val + SPREAD_W * ( ml + mr ) * pen
                        
                        bi = int( math.floor( LS / BW + 0.5 ) ) + HB
                        bi = 0 if bi < 0 else ( NB - 1 if bi >= NB else bi )
                        if bUse[ bi ] == 0 or key < bKey[ bi ]:
                            bUse[ bi ] = 1
                            bKey[ bi ] = key
                            bQ[ bi ] = Q_val
                            bMx[ bi ] = mx
                            bMn[ bi ] = mn
                            bS[ bi ] = tSl + ml * pl + tSr + mr * pr
                            bLn[ bi ] = LS
                            bK[ bi ] = k
                            bO[ bi ] = 0
                            bL[ bi ] = a
                            bR[ bi ] = c
                        
                        # Stacked cut (o=1)
                        pl = tLnr - LS
                        pr = tLnl - LS
                        lnA_st = tLnl + tLnr - LS
                        Q_val = tQl + 2.0 * pl * tSl + ml * pl * pl + tQr + 2.0 * pr * tSr + mr * pr * pr
                        u = tMxl + pl; v = tMxr + pr
                        mx = u if u > v else v
                        u = tMnl + pl; v = tMnr + pr
                        mn = u if u < v else v
                        d = mx - mn - spread_free
                        pen = d * d if d > 0.0 else 0.0
                        key = Q_val + SPREAD_W * ( ml + mr ) * pen
                        
                        bi = int( math.floor( lnA_st / BW + 0.5 ) ) + HB
                        bi = 0 if bi < 0 else ( NB - 1 if bi >= NB else bi )
                        if bUse[ bi ] == 0 or key < bKey[ bi ]:
                            bUse[ bi ] = 1
                            bKey[ bi ] = key
                            bQ[ bi ] = Q_val
                            bMx[ bi ] = mx
                            bMn[ bi ] = mn
                            bS[ bi ] = tSl + ml * pl + tSr + mr * pr
                            bLn[ bi ] = lnA_st
                            bK[ bi ] = k
                            bO[ bi ] = 1
                            bL[ bi ] = a
                            bR[ bi ] = c
            
            oc = 0
            for b in range( NB ):
                if bUse[ b ] != 0:
                    occ[ oc ] = b
                    oc += 1
            m = min( K, oc )
            for gi in range( m ):
                lo = ( gi * oc ) // m
                hi = ( ( gi + 1 ) * oc ) // m
                best = occ[ lo ]
                for q in range( lo + 1, hi ):
                    if bKey[ occ[ q ] ] < bKey[ best ]:
                        best = occ[ q ]
                t = iv * K + gi
                tLn[ t ] = bLn[ best ]
                tA[ t ] = math.exp( bLn[ best ] )
                tS[ t ] = bS[ best ]
                tQ[ t ] = bQ[ best ]
                tMx[ t ] = bMx[ best ]
                tMn[ t ] = bMn[ best ]
                tK[ t ] = bK[ best ]
                tO[ t ] = bO[ best ]
                tL[ t ] = bL[ best ]
                tR[ t ] = bR[ best ]
            cnt[ iv ] = m


def _guarded( fn ):
    # Qt slots must never raise repeatedly (Hydrus's excepthook logs + pops a message every time -> log/disk storm, then freeze/crash).
    # First error: print the traceback once, stop background work; the next re-arrange re-enables it.
    def wrapper( self, *a, **k ):
        if self._failed:
            return
        try:
            return fn( self, *a, **k )
        except Exception:
            self._failed = True
            if self._timer is not None:
                self._timer.stop()
            print( '[MosaicLayout] background layout disabled after an error until the next re-arrange:' )
            traceback.print_exc()
    return wrapper


class MosaicLayout( ThumbnailLayout ):
    """
    Mosaic Layout with True Windowed JIT & Tunable Size Equality
    """
    
    # Tunable Layout Dials
    SCALE_BOOST = 1.35       # Baseline tile size (+35% larger than raw thumb size)
    SPREAD_FREE = 0.0        # Strict equality: zero area divergence allowed for free
    SPREAD_W = 5.0           # Heavy penalty against tiles diverging from peers
    HEIGHT_PEN = 10.0        # Tight section height anchor to nominal height
    ROWS_PER_SECTION = 5.0   # Deep sections (~1.1-1.3x screen height, ~35-50 items)
    ASPECT_MIN = 0.35        # Prevents extreme tall images from towering
    ASPECT_MAX = 2.80        # Prevents extreme panoramas from blowing out width
    WIDE_EXP_BASE = 0.20     # Softened: wide images won't demand massive area
    TALL_EXP_BASE = 0.22     # Softened: tall images won't demand massive area
    SHAPE_CAP = 1.50         # Strictly caps extreme images at 1.5x area (was 2.4x)
    BLOCK_SIZE = 96          # Items per processing block (~2 full sections)
    LOOKAHEAD_SCREENS = 1.0  # blocks this many screens above/below the viewport are solved and placed
    MAX_WINDOW_BLOCKS = 16   # hard cap on blocks placed at once, whatever rect the view reports
    MAX_QUEUED = 8           # hard cap on blocks waiting in the worker pool
    DEBUG = False            # print window/queue stats and swallowed errors to the console

    NMAX = 16
    K = 8
    NB = 33
    BW = 0.2
    HB = 16
    
    def __init__( self, rows_per_section: float | None = None, target_tile_size: int | None = None ):
        super().__init__()
        self._rows_per_section = rows_per_section if rows_per_section is not None else self.ROWS_PER_SECTION
        self._target_tile_size = target_tile_size
        self._params = None
        
        self._thumb_centers = []
        self._thumb_rects = []
        self._col_width = 0
        self._row_height = 0
        self._total_bounds = QC.QRectF( 0, 0, 0, 0 )
        
        # Async JIT state
        self._gen = 0
        self._thumbs = []
        self._aspects = []
        self._heights = []
        self._prefix = [ 0 ]
        self._res = {}
        self._placed = {}
        self._shown = set()
        self._solve_args = None
        self._pad = 0
        self._vis_rect = QC.QRectF( 0, 0, 1, 1 )
        self._connected_view = None
        self._busy = False
        self._failed = False
        
        self._timer = None
        self._inflight = {}
        self._queued = set()
        
        # Buffers: NumPy if Numba is active, plain lists otherwise
        use_np = HAVE_NUMBA
        TLEN = self.NMAX * ( self.NMAX + 1 ) * self.K
        if use_np:
            f = lambda n: np.zeros( n, dtype = np.float64 )
            i8 = lambda n: np.zeros( n, dtype = np.int8 )
            u8 = lambda n: np.zeros( n, dtype = np.uint8 )
            i16 = lambda n: np.zeros( n, dtype = np.int16 )
        else:
            f = lambda n: [ 0.0 ] * n
            i8 = u8 = i16 = lambda n: [ 0 ] * n
            
        self.tA, self.tLn, self.tS, self.tQ, self.tMx, self.tMn = ( f( TLEN ) for _ in range( 6 ) )
        self.tK, self.tO, self.tL, self.tR = ( i8( TLEN ) for _ in range( 4 ) )
        self.cnt = u8( self.NMAX * ( self.NMAX + 1 ) )
        self.AR, self.LT = f( self.NMAX ), f( self.NMAX )
        self.MC = i16( self.NMAX + 2 )
        self.bUse = u8( self.NB )
        self.bQ, self.bS, self.bLn, self.bKey, self.bMx, self.bMn = ( f( self.NB ) for _ in range( 6 ) )
        self.bK, self.bO, self.bL, self.bR, self.occ = ( i8( self.NB ) for _ in range( 5 ) )

        glen = 8 * self.K
        self.gA, self.gLn, self.gS, self.gQ, self.gMx, self.gMn = ( f( glen ) for _ in range( 6 ) )
        self.gC = u8( 8 )
        self.gx, self.gy, self.gw, self.gh = ( i16( 8 ) for _ in range( 4 ) )
        self.gE = i8( 8 )

    @staticmethod
    def _cut( length: int, f: float ) -> int:
        return max( 1, min( length - 1, round( length * f ) ) )

    def _init_items( self, n: int ):
        for j in range( n ):
            iv = j * ( self.NMAX + 1 ) + j + 1
            t = iv * self.K
            self.cnt[ iv ] = 1
            self.tA[ t ] = self.AR[ j ]
            self.tLn[ t ] = math.log( self.AR[ j ] )
            self.tS[ t ] = -self.LT[ j ]
            self.tQ[ t ] = self.LT[ j ] * self.LT[ j ]
            self.tMx[ t ] = -self.LT[ j ]
            self.tMn[ t ] = -self.LT[ j ]

    def _fill_intervals( self, n: int ):
        _numba_fill_intervals(
            n, self.K, self.NB, self.BW, self.HB, self.NMAX, float( self.SPREAD_W ), float( self.SPREAD_FREE ),
            self.tA, self.tLn, self.tS, self.tQ, self.tMx, self.tMn, self.tK, self.tO, self.tL, self.tR, self.cnt, self.MC,
            self.bUse, self.bQ, self.bS, self.bLn, self.bKey, self.bMx, self.bMn, self.bK, self.bO, self.bL, self.bR, self.occ
        )

    def _snap( self ):
        if HAVE_NUMBA:
            return ( self.tA.copy(), self.tK.copy(), self.tO.copy(), self.tL.copy(), self.tR.copy() )
        return ( self.tA[:], self.tK[:], self.tO[:], self.tL[:], self.tR[:] )

    def _emit_tight( self, i: int, j: int, e: int, x: int, y: int, w: int, h: int, on_leaf ):
        if j - i == 1:
            on_leaf( i, e, x, y, w, h )
            return
        b = ( i * ( self.NMAX + 1 ) + j ) * self.K + e
        k = int( self.tK[ b ] )
        l = ( i * ( self.NMAX + 1 ) + k ) * self.K + int( self.tL[ b ] )
        r = ( k * ( self.NMAX + 1 ) + j ) * self.K + int( self.tR[ b ] )
        Al, Ar = self.tA[ l ], self.tA[ r ]
        if self.tO[ b ]:
            ch = self._cut( h, Ar / ( Al + Ar ) )
            self._emit_tight( i, k, int( self.tL[ b ] ), x, y, w, ch, on_leaf )
            self._emit_tight( k, j, int( self.tR[ b ] ), x, y + ch, w, h - ch, on_leaf )
        else:
            cw = self._cut( w, Al / ( Al + Ar ) )
            self._emit_tight( i, k, int( self.tL[ b ] ), x, y, cw, h, on_leaf )
            self._emit_tight( k, j, int( self.tR[ b ] ), x + cw, y, w - cw, h, on_leaf )

    def _solve_block( self, b_idx, aspects, scene_w, base_tile_w, vh, rows_per_section ):
        start = b_idx * self.BLOCK_SIZE
        n_block = len( aspects )
        cells, secs = [], []
        
        t = max( 70, min( round( base_tile_w * self.SCALE_BOOST ), scene_w / 2.2 ) )
        A0 = t * t
        
        view_aspect = scene_w / max( 1.0, vh )
        wide_factor = min( 1.25, max( 1.0, math.sqrt( view_aspect ) ) )
        tall_factor = min( 1.25, max( 1.0, math.sqrt( 1.0 / view_aspect ) ) )
        wide_exp = self.WIDE_EXP_BASE * wide_factor
        tall_exp = self.TALL_EXP_BASE * tall_factor
        
        # Area weights strictly bounded to enforce tile size equality
        weights = [ 0.0 ] * n_block
        for i in range( n_block ):
            a = aspects[ i ]
            if a < 1.0:
                shape = min( self.SHAPE_CAP, math.pow( 1.0 / a, tall_exp ) )
            else:
                shape = min( self.SHAPE_CAP, math.pow( a, wide_exp ) )
            weights[ i ] = max( 1.0, shape )

        # Section height target: ~1.1-1.3x screen height
        target_hs = max( rows_per_section * t, vh * 1.10 )
        Hmax = max( 4.0 * t, vh * 1.45 )
        Hs = max( 2.5 * t, min( target_hs, 0.95 * Hmax ) )
        
        ptr = 0
        curr_y = 0
        sec_n = 0
        
        while ptr < n_block:
            rem = n_block - ptr
            ptr0 = ptr
            nScale = 1.0
            
            while True:
                ptr = ptr0
                wsum = 0.0
                limit_c = min( 8, rem )
                for c_idx in range( limit_c ):
                    wsum += weights[ ptr + c_idx ]
                c = max( 1, limit_c )
                
                avg_area = A0 * wsum / c
                n = max( 6, min( 55, round( scene_w * Hs / avg_area * nScale ) ) )
                if rem - n < 5:
                    n = rem
                
                G = max( 1, min( 8, math.ceil( n / 9.0 ) ) )
                gsz, gst = [], []
                s0 = 0
                for g in range( G ):
                    m = n // G + ( 1 if g < ( n % G ) else 0 )
                    gsz.append( m )
                    gst.append( s0 )
                    s0 += m
                
                tot = sum( weights[ ptr + j ] for j in range( n ) )
                
                # Level 1: Group trees (snapshotted to avoid redundant second DP pass)
                snaps = []
                for g in range( G ):
                    st0, m = gst[ g ], gsz[ g ]
                    for j in range( m ):
                        self.AR[ j ] = aspects[ ptr + st0 + j ]
                        self.LT[ j ] = math.log( weights[ ptr + st0 + j ] / tot )
                        self.MC[ j + 1 ] = j + 1
                    self._init_items( m )
                    self._fill_intervals( m )
                    snaps.append( self._snap() )
                    self.gC[ g ] = int( self.cnt[ m ] )
                    
                    o_base, m_base = g * self.K, m * self.K
                    for e in range( self.cnt[ m ] ):
                        t_idx, o_idx = m_base + e, o_base + e
                        self.gA[ o_idx ] = self.tA[ t_idx ]
                        self.gLn[ o_idx ] = self.tLn[ t_idx ]
                        self.gS[ o_idx ] = self.tS[ t_idx ]
                        self.gQ[ o_idx ] = self.tQ[ t_idx ]
                        self.gMx[ o_idx ] = self.tMx[ t_idx ]
                        self.gMn[ o_idx ] = self.tMn[ t_idx ]
                
                # Level 2: Block tree
                self.MC[ 0 ] = 0
                for g in range( G ):
                    self.MC[ g + 1 ] = self.MC[ g ] + gsz[ g ]
                    iv = g * ( self.NMAX + 1 ) + g + 1
                    g_cnt = self.gC[ g ]
                    self.cnt[ iv ] = g_cnt
                    iv_base, o_base = iv * self.K, g * self.K
                    for e in range( g_cnt ):
                        t_idx, o_idx = iv_base + e, o_base + e
                        self.tA[ t_idx ] = self.gA[ o_idx ]
                        self.tLn[ t_idx ] = self.gLn[ o_idx ]
                        self.tS[ t_idx ] = self.gS[ o_idx ]
                        self.tQ[ t_idx ] = self.gQ[ o_idx ]
                        self.tMx[ t_idx ] = self.gMx[ o_idx ]
                        self.tMn[ t_idx ] = self.gMn[ o_idx ]
                
                self._fill_intervals( G )
                
                H0 = A0 * tot / scene_w
                bc = float( 'inf' )
                best_rootE, best_H = 0, 0
                g_base = G * self.K
                
                for e in range( self.cnt[ G ] ):
                    idx = g_base + e
                    hh = scene_w / self.tA[ idx ]
                    d = math.log( hh / H0 )
                    c_val = (
                        ( self.tQ[ idx ] + self.SPREAD_W * n * _numba_spread_pen( self.tMx[ idx ], self.tMn[ idx ], self.SPREAD_FREE ) ) / n
                        + self.HEIGHT_PEN * d * d + ( 20.0 * ( math.log( hh / Hmax ) ** 2 ) if hh > Hmax else 0.0 )
                    )
                    
                    if c_val < bc:
                        bc = c_val
                        best_rootE = e
                        best_H = max( 24, round( hh ) )
                
                H = best_H
                if H > Hmax * 1.05 and n > 5 and nScale > 0.3:
                    nScale *= max( 0.5, min( 0.9, Hmax / H ) )
                    continue
                break
            
            # Emit Level 2 block tree -> group rects
            def leaf_group( i, e, x_pos, y_pos, w_val, h_val ):
                self.gx[ i ] = x_pos
                self.gy[ i ] = y_pos
                self.gw[ i ] = w_val
                self.gh[ i ] = h_val
                self.gE[ i ] = e
            
            self._emit_tight( 0, G, best_rootE, 0, curr_y, scene_w, H, leaf_group )
            
            # Emit Level 1 leaf tiles from snapshots
            live = ( self.tA, self.tK, self.tO, self.tL, self.tR )
            for g in range( G ):
                m = gsz[ g ]
                base_ptr = start + ptr + gst[ g ]
                def leaf_tile( i, e, x_pos, y_pos, w_val, h_val, bp = base_ptr ):
                    cells.append( ( bp + i - start, x_pos, y_pos, w_val, h_val, sec_n ) )
                
                self.tA, self.tK, self.tO, self.tL, self.tR = snaps[ g ]
                self._emit_tight( 0, m, int( self.gE[ g ] ), int( self.gx[ g ] ), int( self.gy[ g ] ), int( self.gw[ g ] ), int( self.gh[ g ] ), leaf_tile )
            self.tA, self.tK, self.tO, self.tL, self.tR = live
            
            secs.append( ( curr_y, H ) )
            curr_y += H
            ptr += n
            sec_n += 1

        return cells, secs, curr_y

    # region Windowed JIT Orchestration (Only Solves Viewport + Buffer)
    
    _pool = None
    
    @classmethod
    def _get_pool( cls ):
        if cls._pool is None:
            cls._pool = ThreadPoolExecutor( max_workers = 2, thread_name_prefix = 'mosaic' )
        return cls._pool
    
    def _rebuild_prefix( self ):
        pre = [ 0 ]
        acc = 0
        for h in self._heights:
            acc += h
            pre.append( acc )
        self._prefix = pre
    
    def _place( self, b ):
        if b not in self._res:
            return
        cells, _secs, _H = self._res[ b ]
        y_base = self._prefix[ b ]
        st = b * self.BLOCK_SIZE
        mx = self._params.scene_margin_horizontal
        pad = self._pad
        
        for li, x, y, w, h, s in cells:
            idx = st + li
            if idx >= len( self._thumbs ):
                continue
            t = self._thumbs[ idx ]
            
            tw = max( 16, w - 2 * pad )
            th = max( 16, h - 2 * pad )
            px = mx + x + pad
            py = y_base + y + pad
            
            try:
                t._index = idx
                if t.width != tw or t.height != th:
                    # MUST come before the bounding rect changes: Qt's scene index (BSP tree) files each item under its current
                    # bounding rect. Resizing silently leaves stale entries that dangle once the item is removed/deleted, and
                    # the next scene().items() call (the panel's _OnVisibleRectChanged) segfaults.
                    t.prepareGeometryChange()
                    t.width = tw
                    t.height = th
                t.setPos( px, py )
                t.setVisible( True )
                t._mz_hidden = False
                self._shown.add( t )
                self._thumb_centers[ idx ] = ( px + tw / 2.0, py + th / 2.0 )
                self._thumb_rects[ idx ] = ( px, py, tw, th )
            except ( RuntimeError, ReferenceError ):
                pass
                
        self._placed[ b ] = y_base
    
    def _unplace( self, b ):
        if b not in self._res:
            self._placed.pop( b, None )
            return
        cells = self._res[ b ][ 0 ]
        st = b * self.BLOCK_SIZE
        for c in cells:
            idx = st + c[ 0 ]
            if idx < len( self._thumbs ):
                t = self._thumbs[ idx ]
                try:
                    t.setVisible( False )
                    t._mz_hidden = True
                except ( RuntimeError, ReferenceError ):
                    pass
                self._shown.discard( t )
            if idx < len( self._thumb_centers ):
                self._thumb_centers[ idx ] = None
                self._thumb_rects[ idx ] = None
        self._placed.pop( b, None )
    
    def _window_blocks( self ):
        # One place that decides which blocks are live. Sized from the view's real height and the TOP of the reported rect only,
        # so a odd/stale/huge rect can never turn into "solve and place everything".
        pre, nb = self._prefix, len( self._heights )
        if nb == 0 or self._params is None:
            return 0, -1
        top = self._vis_rect.top()
        vh = self._params.viewport_height
        pad = vh * self.LOOKAHEAD_SCREENS
        b0 = max( 0, min( nb - 1, bisect.bisect_right( pre, top - pad ) - 1 ) )
        b1 = max( b0, min( nb - 1, bisect.bisect_right( pre, top + vh + pad ) - 1 ) )
        if b1 - b0 + 1 > self.MAX_WINDOW_BLOCKS:
            c = max( 0, min( nb - 1, bisect.bisect_right( pre, top + vh / 2 ) - 1 ) )
            b0 = max( 0, min( c - self.MAX_WINDOW_BLOCKS // 2, nb - self.MAX_WINDOW_BLOCKS ) )
            b1 = min( nb - 1, b0 + self.MAX_WINDOW_BLOCKS - 1 )
        return b0, b1
    
    def _sync_window( self ):
        b0, b1 = self._window_blocks()
        want = { b for b in range( b0, b1 + 1 ) if b in self._res }
        
        for b in [ b for b in self._placed if b not in want ]:
            self._unplace( b )
        for b in want:
            if self._placed.get( b ) != self._prefix[ b ]:
                self._place( b )
        
        if self.DEBUG:
            print( f'[mosaic] window {b0}-{b1} of {len( self._heights )}  placed={len( self._placed )} shown={len( self._shown )} queued={len( self._queued )} top={self._vis_rect.top():.0f}' )
    
    def _pump( self ):
        """Queues missing blocks inside the live window, nearest to the viewport first, never more than MAX_QUEUED at a time."""
        b0, b1 = self._window_blocks()
        room = self.MAX_QUEUED - len( self._queued )
        if room <= 0 or b1 < b0:
            return
        
        c = ( b0 + b1 ) // 2
        needed = [ b for b in range( b0, b1 + 1 ) if b not in self._res and b not in self._queued ]
        needed.sort( key = lambda b: abs( b - c ) )
        
        pool = self._get_pool()
        BS = self.BLOCK_SIZE
        for b in needed[ : room ]:
            job = ( self._gen, [ ( b, self._aspects[ b * BS : ( b + 1 ) * BS ] ) ], *self._solve_args )
            self._inflight[ pool.submit( _mosaic_worker, job ) ] = [ b ]
            self._queued.add( b )
    
    def _commit( self ):
        self._rebuild_prefix()
        view = self._connected_view
        
        self._busy = True
        try:
            bounds = QC.QRectF( 0, 0, self._params.viewport_width, self._prefix[ -1 ] )
            if view is not None:
                was_blocked = view.blockSignals( True )
                view.setSceneRect( bounds )
                view.blockSignals( was_blocked )
            self._total_bounds = bounds
            self._sync_window()
        finally:
            self._busy = False
    
    @_guarded
    def _tick( self ):
        if self._busy:
            return
        changed = False
        current_gen = self._gen
        BS = self.BLOCK_SIZE
        
        for f in [ f for f in self._inflight if f.done() ]:
            chunk = self._inflight.pop( f )
            self._queued.difference_update( chunk )
            if f.cancelled():
                continue
            try:
                res_gen, results = f.result()
            except Exception:
                res_gen, results = current_gen, [ ( b, self._solve_block( b, self._aspects[ b * BS : ( b + 1 ) * BS ], *self._solve_args ) ) for b in chunk ]
            if res_gen != current_gen:
                continue
            for b, res in results:
                self._res[ b ] = res
                self._heights[ b ] = res[ 2 ]
            changed = True
            
        if changed:
            self._commit()
        self._pump()
        if not self._queued and not self._inflight:
            self._timer.stop()
    
    @_guarded
    def _on_visible_rect_changed( self, rect: QC.QRectF ):
        self._vis_rect = QC.QRectF( rect )
        if self._busy or not self._heights:
            return
        self._sync_window()
        self._pump()
        if not self._timer.isActive():
            self._timer.start()
    
    # endregion

    def ArrangeThumbnails( self, thumbnails, params: LayoutParams ) -> QC.QRectF:
        if self._timer is None:
            self._timer = QC.QTimer()
            self._timer.setInterval( 15 )
            self._timer.timeout.connect( self._tick )
        self._busy = True
        self._failed = False
        self._gen += 1
        
        try:
            for f in self._inflight:
                f.cancel()
            self._inflight.clear()
            self._queued.clear()
            self._res.clear()
            self._placed.clear()
            
            for t in self._shown:
                try:
                    t.setVisible( False )
                    t._mz_hidden = True
                except ( RuntimeError, ReferenceError ):
                    pass
            self._shown.clear()
            
            self._params = params
            self._thumbs = thumbnails
            count = len( thumbnails )
            self._pad = params.thumb_margin_horizontal
            
            if count == 0:
                self._thumb_centers = []
                self._thumb_rects = []
                self._heights = []
                self._prefix = [ 0 ]
                self._timer.stop()
                return QC.QRectF( 0, 0, params.viewport_width, params.viewport_height )
            
            if not self._connected_view and len( thumbnails ) > 0:
                view = getattr( thumbnails[ 0 ], '_view', None )
                if view and hasattr( view, 'visibleRectChanged' ):
                    view.visibleRectChanged.connect( self._on_visible_rect_changed )
                    # Disabling AnchorViewCenter stops Qt from pulling the scrollbar when heights refine
                    view.setResizeAnchor( QW.QGraphicsView.ViewportAnchor.NoAnchor )
                    view.setTransformationAnchor( QW.QGraphicsView.ViewportAnchor.NoAnchor )
                    self._connected_view = view
            
            if self._target_tile_size is not None:
                base_tile_w = self._target_tile_size
                base_tile_h = self._target_tile_size
            else:
                base_tile_w = round( params.thumb_width * params.zoom )
                base_tile_h = round( params.thumb_height * params.zoom )
                
            self._col_width = base_tile_w + 2 * params.thumb_margin_horizontal
            self._row_height = base_tile_h + 2 * params.thumb_margin_vertical
            scene_w = max( 100, params.viewport_width - 2 * params.scene_margin_horizontal )
            
            t = max( 70, min( round( base_tile_w * self.SCALE_BOOST ), scene_w / 2.2 ) )
            self._solve_args = ( scene_w, base_tile_w, params.viewport_height, self._rows_per_section )
            
            self._aspects = [ max( self.ASPECT_MIN, min( self.ASPECT_MAX, max( 1, th.res_x ) / max( 1, th.res_y ) ) ) for th in thumbnails ]
            
            view_aspect = scene_w / max( 1.0, params.viewport_height )
            wide_factor = min( 1.25, max( 1.0, math.sqrt( view_aspect ) ) )
            tall_factor = min( 1.25, max( 1.0, math.sqrt( 1.0 / view_aspect ) ) )
            wide_exp = self.WIDE_EXP_BASE * wide_factor
            tall_exp = self.TALL_EXP_BASE * tall_factor

            a = np.array( self._aspects )
            shape = np.where( a < 1.0, np.minimum( self.SHAPE_CAP, a ** -tall_exp ), np.minimum( self.SHAPE_CAP, a ** wide_exp ) )
            shape = np.maximum( 1.0, shape )
            
            sums = np.add.reduceat( shape, np.arange( 0, count, self.BLOCK_SIZE ) )
            self._heights = np.maximum( 48, np.rint( t * t * sums / scene_w ) ).astype( int ).tolist()
            self._rebuild_prefix()
            
            for th in thumbnails:
                if not getattr( th, '_mz_hidden', False ):
                    try:
                        th.setVisible( False )
                        th._mz_hidden = True
                    except ( RuntimeError, ReferenceError ):
                        pass
            
            self._thumb_centers = [ None ] * count
            self._thumb_rects = [ None ] * count
            
            # CRITICAL RESIZE FIX: Determine the block currently in view and solve it IMMEDIATELY!
            # If user is at top -> solves Block 0.
            # If user is scrolled down -> solves the active block right at their scroll position!
            scroll_top = self._vis_rect.top()
            active_b = max( 0, min( len( self._heights ) - 1, bisect.bisect_right( self._prefix, max( 0.0, scroll_top ) ) - 1 ) )
            
            res = self._solve_block( active_b, self._aspects[ active_b * self.BLOCK_SIZE : ( active_b + 1 ) * self.BLOCK_SIZE ], *self._solve_args )
            self._res[ active_b ] = res
            self._heights[ active_b ] = res[ 2 ]
            self._rebuild_prefix()
            
            self._total_bounds = QC.QRectF( 0, 0, params.viewport_width, self._prefix[ -1 ] )
            self._sync_window()
            self._pump()
            self._timer.start()
            return self._total_bounds
        finally:
            self._busy = False

    def MoveFromIndex( self, original_index: int, direction: int ) -> int:
        if not self._thumb_centers or original_index < 0 or original_index >= len( self._thumb_centers ):
            return original_index
        
        count = len( self._thumb_centers )
        if self._thumb_centers[ original_index ] is None:   # focused tile is outside the live window
            return original_index
        cx, cy = self._thumb_centers[ original_index ]
        _cur_x, _cur_y, _cur_w, cur_h = self._thumb_rects[ original_index ]
        best_idx = None
        best_dist = float( 'inf' )
        
        for idx, other_center in enumerate( self._thumb_centers ):
            if idx == original_index or other_center is None:
                continue
            ox, oy = other_center
            dx = ox - cx
            dy = oy - cy
            
            if direction == CAC.MOVE_LEFT:
                if dx >= -5 or abs( dy ) > cur_h * 0.65: continue
                dist = abs( dx ) + abs( dy ) * 2.0
            elif direction == CAC.MOVE_RIGHT:
                if dx <= 5 or abs( dy ) > cur_h * 0.65: continue
                dist = abs( dx ) + abs( dy ) * 2.0
            elif direction == CAC.MOVE_UP:
                if dy >= -5: continue
                dist = abs( dx ) * 1.5 + abs( dy )
            elif direction == CAC.MOVE_DOWN:
                if dy <= 5: continue
                dist = abs( dx ) * 1.5 + abs( dy )
            else:
                return original_index
            
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
                
        if best_idx is not None:
            return best_idx
            
        if direction == CAC.MOVE_RIGHT:
            return min( count - 1, original_index + 1 )
        elif direction == CAC.MOVE_LEFT:
            return max( 0, original_index - 1 )
            
        return original_index

    def JumpPage( self, scene_rect: QC.QRectF, media_index: int, direction: int, percent_visible: float ) -> int:
        if not self._thumb_centers or media_index < 0 or media_index >= len( self._thumb_centers ):
            return media_index
        
        if self._thumb_centers[ media_index ] is None:
            return media_index
        cx, cy = self._thumb_centers[ media_index ]
        target_y = cy + direction * self._params.viewport_height
        best_idx = media_index
        best_dist = float( 'inf' )
        
        for idx, other_center in enumerate( self._thumb_centers ):
            if other_center is None:
                continue
            ox, oy = other_center
            dist = abs( ox - cx ) * 1.5 + abs( oy - target_y )
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
                
        return best_idx

    def ThumbnailSpanDimensions( self, thumbnail ) -> tuple[int, int]:
        if thumbnail is not None and getattr( thumbnail, 'width', 0 ) > 0:
            margin_h = self._params.thumb_margin_horizontal if self._params else 0
            margin_v = self._params.thumb_margin_vertical if self._params else 0
            return thumbnail.width + 2 * margin_h, thumbnail.height + 2 * margin_v
        return self._col_width, self._row_height


_WORKER_TLS = threading.local()

def _mosaic_worker( job ):
    gen_id, blocks, *args = job
    lay = getattr( _WORKER_TLS, 'lay', None )
    if lay is None:
        lay = _WORKER_TLS.lay = MosaicLayout()
    return gen_id, [ ( b, lay._solve_block( b, aspects, *args ) ) for b, aspects in blocks ]
