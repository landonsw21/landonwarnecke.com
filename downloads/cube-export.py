# cube export — reusable KeyShot cube captures for Fisheye Studio
# Scene/projection helpers adapted from Perspective Studio fisheye v0.6.1.
# Run inside KeyShot. The editor is bundled as a fallback and also supplied separately.
# Only duplicates recorded in this run are cleaned up; originals are never deleted.
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import zlib

try:
    import lux
except ImportError:  # outside KeyShot: the lens math and image code still work (tests)
    lux = None
try:
    import luxmath
except ImportError:
    luxmath = None

TITLE = "cube export"
PI2 = math.pi / 2.0
DEG = math.pi / 180.0

MODES = ["4-point fisheye", "5-point", "6-point (whole sphere)", "4-point panorama"]
MODE_KEYS = ["4pt", "5pt", "6pt", "pano"]


# ---------------------------------------------------------------- lens math
# A port of the site's lenses (twoAxisLens, sphereCam and panoCam), measured in units where
# the lens spreads one radian per unit at its center. Camera space: x right, y up, z ahead.

def stretch_of(pct):
    """Curvature in percent to a side's stretch: 100% is 1 (an even fisheye), lower is straighter."""
    return 100.0 / max(0.01, pct)


def clamp_stretch(s):
    return min(1e4, max(1e-3, s))


def _expm1(x):
    try:
        return math.expm1(x)
    except OverflowError:
        return float("inf")


def rear_kappa(back):
    """How fast the rear half eases out so the back rim sits `back` times as far as the 90-degree ring."""
    m = min(50.0, max(1.05, back)) - 1.0

    def f(k):
        return 1.0 if abs(k) < 1e-9 else -_expm1(-k) / k

    lo, hi = -60.0, 60.0
    for _ in range(64):
        mid = (lo + hi) / 2.0
        if f(mid) > m:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


class Lens(object):
    """unproj(x, y) gives the direction seen at lens point (x, y), or None outside the picture."""

    def __init__(self, mode="4pt", hc=100.0, vc=100.0, coverage=180.0, back=2.0, pano_height=45.0):
        if mode not in MODE_KEYS:
            raise ValueError("unknown mode %r" % (mode,))
        self.mode = mode
        h, v = stretch_of(hc), stretch_of(vc)
        self.sR = self.sL = clamp_stretch(h)
        self.sU = self.sD = clamp_stretch(v)
        self.k = None
        self.th_max = PI2
        if mode == "5pt":
            self.th_max = min(max(10.0, min(359.0, coverage)) / 2.0 * DEG, math.pi * 0.999)
        elif mode == "6pt":
            self.th_max = math.pi
            self.k = rear_kappa(back)
        elif mode == "pano":
            self.a = min(1e4, stretch_of(hc))
            self.e_max = max(1.0, min(80.0, pano_height)) * DEG

    # --- the two-axis lens (4-, 5- and 6-point)
    def reach(self, cx, sy):
        return 1.0 / math.hypot(cx / (self.sR if cx >= 0 else self.sL), sy / (self.sU if sy >= 0 else self.sD))

    def tk(self, t):
        """Profile: equidistant to 90 degrees; past it the 6-point rear half eases out."""
        if t <= PI2 or self.k is None:
            return t
        q, v = self.k, (t - PI2) / PI2
        return PI2 * (1 + (v if abs(q) < 1e-9 else -_expm1(-q * v) / q))

    def itk(self, r):
        if r <= PI2 or self.k is None:
            return r
        q, v = self.k, r / PI2 - 1
        if abs(q) < 1e-9:
            return PI2 * (1 + v)
        if q > 0 and q * v >= 1:
            return float("inf")
        return PI2 * (1 - math.log1p(-q * v) / q)

    def place(self, th, cx, sy):
        A = self.reach(cx, sy)
        r = A * self.tk(math.atan2(math.sin(th), A * math.cos(th)))
        return (r * cx, r * sy)

    # --- the panorama
    def p_base(self, y):
        a = self.a
        if a == 1:
            return y
        k = math.floor(y / (2 * math.pi) + 0.5)
        r = y - k * 2 * math.pi
        return a * math.atan2(math.sin(r), a * math.cos(r)) + k * 2 * math.pi * a

    def p_unbase(self, t):
        a = self.a
        if a == 1:
            return t
        return math.atan2(a * math.sin(t / a), math.cos(t / a))

    def p_tall(self, y):
        a = self.a
        if a == 1:
            return 1.0
        c, s = math.cos(y), math.sin(y)
        return math.sqrt(a * a / (a * a * c * c + s * s))

    # ---
    def unproj(self, x, y):
        if self.mode == "pano":
            half = math.pi * self.a
            if x < -half or x > half:
                return None
            yaw = self.p_unbase(x)
            e = math.atan(y / self.p_tall(yaw))
            if abs(e) > self.e_max:
                return None
            ce = math.cos(e)
            return (ce * math.sin(yaw), math.sin(e), ce * math.cos(yaw))
        r = math.hypot(x, y)
        if r < 1e-12:
            return (0.0, 0.0, 1.0)
        cx, sy = x / r, y / r
        A = self.reach(cx, sy)
        t = self.itk(r / A)
        if t > math.pi:
            return None
        th = math.atan2(A * math.sin(t), math.cos(t))
        if th > self.th_max + 1e-12:
            return None
        sn = math.sin(th)
        return (sn * cx, sn * sy, math.cos(th))

    def proj(self, D):
        """Lens point of direction D (used by the tests and the bounds)."""
        if self.mode == "pano":
            yaw = math.atan2(D[0], D[2])
            e = math.atan2(D[1], math.hypot(D[0], D[2]))
            return (self.p_base(yaw), self.p_tall(yaw) * math.tan(e))
        rho = math.hypot(D[0], D[1])
        if rho == 0:
            return (0.0, 0.0) if D[2] > 0 else None
        return self.place(math.atan2(rho, D[2]), D[0] / rho, D[1] / rho)

    def bounds(self):
        """(xmin, xmax, ymin, ymax) of the picture."""
        if self.mode == "pano":
            half = math.pi * self.a
            tall = max(self.p_tall(i * math.pi / 360) for i in range(-360, 361))
            top = tall * math.tan(self.e_max)
            return (-half, half, -top, top)
        th = min(self.th_max, math.pi * 0.99999)
        xs, ys = [], []
        for i in range(1440):
            a = i * math.pi / 720
            px, py = self.place(th, math.cos(a), math.sin(a))
            xs.append(px)
            ys.append(py)
        return (min(xs), max(xs), min(ys), max(ys))


# ---------------------------------------------------------------- cube faces
# Faces are perspective renders from the camera's position, 90 degrees wide plus a small
# margin. In camera space (x right, y up, z ahead) each face looks along an axis.
FACES = ["front", "right", "back", "left", "up", "down"]
FRONT, RIGHT, BACK, LEFT, UP, DOWN = range(6)


def face_of(x, y, z):
    """The face that sees direction (x, y, z), and the point (X, Y) on it (-1..1 is the 90 degrees)."""
    ax, ay, az = abs(x), abs(y), abs(z)
    if az >= ax and az >= ay:
        if z > 0:
            return FRONT, x / z, y / z
        return BACK, x / z, -y / z
    if ax >= ay:
        if x > 0:
            return RIGHT, -z / x, y / x
        return LEFT, -z / x, -y / x
    if y > 0:
        return UP, x / y, -z / y
    return DOWN, -x / y, -z / y


def face_frames(f, r, u):
    """World direction and up vector of each face, given the camera's ahead f, right r and up u."""
    neg = lambda v: (-v[0], -v[1], -v[2])
    return {
        FRONT: (f, u), BACK: (neg(f), u),
        RIGHT: (r, u), LEFT: (neg(r), u),
        UP: (u, neg(f)), DOWN: (neg(u), f),
    }


def faces_needed(lens, b, n=160):
    xmin, xmax, ymin, ymax = b
    need = set()
    h = max(2, int(n * (ymax - ymin) / max(1e-9, xmax - xmin)))
    for j in range(h + 1):
        for i in range(n + 1):
            d = lens.unproj(xmin + (xmax - xmin) * i / n, ymin + (ymax - ymin) * j / h)
            if d is not None:
                need.add(face_of(*d)[0])
    if lens.mode != "pano":  # the rim itself
        th = min(lens.th_max, math.pi * 0.99999)
        for i in range(720):
            a = i * math.pi / 360
            sn = math.sin(th)
            need.add(face_of(sn * math.cos(a), sn * math.sin(a), math.cos(th))[0])
    return sorted(need)


def vec(v):
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except TypeError:
        return (float(v.x), float(v.y), float(v.z))


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    l = math.sqrt(dot(a, a))
    return (a[0] / l, a[1] / l, a[2] / l) if l > 1e-12 else None


WORLD_UP = (0.0, 1.0, 0.0)  # KeyShot scenes are Y-up


def wrap90(a):
    """Angle in degrees folded into (-45, 45]."""
    a = math.fmod(a + 45.0, 90.0)
    if a <= 0:
        a += 90.0
    return a - 45.0


def camera_basis(direction, up, level=True, square=False):
    """Ahead, right and up of the fisheye. level keeps the horizon through the middle;
    square also turns it to face straight along the scene's nearest X or Z axis."""
    f = norm(direction)
    u = norm(up) or WORLD_UP
    if level or square:
        flat = norm((f[0], 0.0, f[2]))
        if flat is None:  # looking straight up or down: keep the camera's own heading
            flat = norm((u[0], 0.0, u[2])) if f[1] < 0 else norm((-u[0], 0.0, -u[2]))
            flat = flat or (0.0, 0.0, -1.0)
        f = flat
        if square:
            psi = math.atan2(f[0], f[2])
            psi = round(psi / PI2) * PI2
            f = (math.sin(psi), 0.0, math.cos(psi))
        u = WORLD_UP
    else:
        u = norm((u[0] - f[0] * dot(u, f), u[1] - f[1] * dot(u, f), u[2] - f[2] * dot(u, f))) or WORLD_UP
    r = norm(cross(f, u))
    u = cross(r, f)
    return f, r, u


def site_turn(f, r, mode):
    """The site's Turn (4-point) that lines its grid up with the scene's X and Z axes, or how far
    the view is turned away from facing an axis (5- and 6-point)."""
    yaw_x = math.degrees(math.atan2(r[0], f[0]))  # where the scene's X axis is, seen from the camera
    if mode in ("4pt", "pano"):
        return wrap90(yaw_x + 45.0)
    return wrap90(yaw_x)


# ---------------------------------------------------------------- sphere copies
# Before rendering, copies of the chosen models are pasted on a sphere around the camera whose
# radius is the camera's distance to the centre of the model's bounding box. They're spaced
# like the faces of a polyhedron: exactly on a solid's faces when the count matches one,
# otherwise spread by mutual repulsion (the Thomson problem). "Upright" copies keep the original's rotation and are only moved;
# "Projected" copies are swung around the camera so each one shows the camera the same side
# the original does, kept level with the scene's Y up. Copies are named "<name>_sphere_001"
# and so on. Matrices here are plain 4x4 lists, column-vector style (p' = A p).

COPY_ORIENTS = ["Upright (keep base orientation)", "Projected (rotate with camera ray)",
                "Camera-facing (minimal rotation)", "Tangent to sphere (forward along tangent)"]
COPY_DISTRIBUTIONS = ["Balanced hybrid (recommended)", "Evenly spaced on 3D sphere (original)", "Evenly spaced in fisheye image (dense rim)"]
COPY_MAX = 5000
_MAT_LAYOUT = None   # where luxmath keeps translation: "row" (elements 12-14) or "col" (3, 7, 11)
_APPEND_MODE = None  # how a relative applyTransform composes: "parent" or "local" space


def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def v_len(a):
    return math.sqrt(dot(a, a))


def v_unit(a):
    n = norm(a)
    if n is None:
        raise ValueError("zero-length vector")
    return n


def m3_mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def m3_transpose(a):
    return [[a[c][r] for c in range(3)] for r in range(3)]


def m3_apply(a, v):
    return tuple(a[r][0] * v[0] + a[r][1] * v[1] + a[r][2] * v[2] for r in range(3))


def m3_axis_angle(axis, angle):
    x, y, z = v_unit(axis)
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]


def m3_rotation_between(a, b):
    """The smallest rotation turning direction a into direction b."""
    a, b = v_unit(a), v_unit(b)
    c = max(-1.0, min(1.0, dot(a, b)))
    if c > 1.0 - 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    if c < -1.0 + 1e-12:
        helper = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 0.0, 1.0)
        return m3_axis_angle(cross(a, helper), math.pi)
    return m3_axis_angle(cross(a, b), math.acos(c))


def m3_look_frame(forward):
    """Columns right, up, forward of a view along forward, level with the world's Y up."""
    f = v_unit(forward)
    r = cross(f, WORLD_UP)
    if v_len(r) < 1e-6:  # straight up or down
        r = cross(f, (0.0, 0.0, 1.0))
    r = v_unit(r)
    u = cross(r, f)
    return [[r[0], u[0], f[0]], [r[1], u[1], f[1]], [r[2], u[2], f[2]]]


def m4_identity():
    return [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def m4_mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def m4_translate(t):
    m = m4_identity()
    m[0][3], m[1][3], m[2][3] = t[0], t[1], t[2]
    return m


def m4_from_m3(r3):
    m = m4_identity()
    for r in range(3):
        m[r][:3] = list(r3[r])
    return m


def m4_apply_point(m, v):
    return tuple(m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] + m[r][3] for r in range(3))


def m4_translation(m):
    return (m[0][3], m[1][3], m[2][3])


def m4_inverse(m):
    """4x4 inverse by Gauss-Jordan with partial pivoting."""
    a = [list(row) + [1.0 if r == c else 0.0 for c in range(4)] for r, row in enumerate(m)]
    for col in range(4):
        p = max(range(col, 4), key=lambda r: abs(a[r][col]))
        if abs(a[p][col]) < 1e-14:
            raise ValueError("matrix is not invertible")
        a[col], a[p] = a[p], a[col]
        piv = a[col][col]
        a[col] = [x / piv for x in a[col]]
        for r in range(4):
            if r != col and a[r][col] != 0.0:
                k = a[r][col]
                a[r] = [x - k * y for x, y in zip(a[r], a[col])]
    return [row[4:] for row in a]


def _flatten(value, out=None):
    out = [] if out is None else out
    if isinstance(value, (list, tuple)):
        for e in value:
            _flatten(e, out)
    else:
        out.append(float(value))
    return out


def _matrix_values(km):
    for get in (lambda: km.val(), lambda: km.data):
        try:
            vals = _flatten(get())
            if len(vals) == 16:
                return vals
        except Exception:
            pass
    raise RuntimeError("couldn't read a luxmath.Matrix")


def _detect_matrix_layout():
    """Where luxmath stores translation, found with a probe matrix."""
    f = _matrix_values(luxmath.Matrix().makeIdentity().translate(luxmath.Vector((1.0, 2.0, 3.0))))
    for layout, idx in (("row", (12, 13, 14)), ("col", (3, 7, 11))):
        if all(abs(f[i] - v) < 1e-6 for i, v in zip(idx, (1.0, 2.0, 3.0))):
            return layout
    raise RuntimeError("unrecognised luxmath.Matrix layout %r" % (f,))


def to_lux_matrix(a):
    if _MAT_LAYOUT == "row":  # luxmath keeps the transpose (row vectors)
        return luxmath.Matrix(tuple(a[c][r] for r in range(4) for c in range(4)))
    return luxmath.Matrix(tuple(a[r][c] for r in range(4) for c in range(4)))


def from_lux_matrix(km):
    f = _matrix_values(km)
    if _MAT_LAYOUT == "row":
        return [[f[c * 4 + r] for c in range(4)] for r in range(4)]
    return [[f[r * 4 + c] for c in range(4)] for r in range(4)]


def _children(node):
    try:
        return list(node.getChildren() or [])
    except Exception:
        return []


def _walk(root):
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(_children(n))


def _parent(node):
    try:
        return node.getParent()
    except Exception:
        return None


def _flag(node, method):
    try:
        return bool(getattr(node, method)())
    except Exception:
        return False


def selected_top_nodes(root):
    """The selected nodes, leaving out any whose ancestor is selected too."""
    try:
        sel = [n for n in (root.getSelected() or []) if hasattr(n, "getID")]
    except Exception:
        sel = []
    if not sel:
        sel = [n for n in _walk(root) if _flag(n, "isSelected")]
    root_id = root.getID()
    nodes, ids = [], set()
    for n in sel:
        nid = n.getID()
        if nid == root_id or nid in ids or is_camera(n) or _flag(n, "isDeleted"):
            continue
        ids.add(nid)
        nodes.append(n)
    top = []
    for n in nodes:
        a, nested, guard = _parent(n), False, 0
        while a is not None and guard < 1000:
            if a.getID() in ids:
                nested = True
                break
            if a.getID() == root_id:
                break
            a, guard = _parent(a), guard + 1
        if not nested:
            top.append(n)
    return top


def world_bbox_center(node):
    try:
        bb = node.getBoundingBox(world=True)
    except TypeError:
        bb = node.getBoundingBox(True)
    return v_scale(v_add(vec(bb[0]), vec(bb[1])), 0.5)


def node_transforms(node):
    """(world, local) as plain matrices."""
    local = from_lux_matrix(node.getTransform())
    try:
        world = from_lux_matrix(node.getTransform(world=True))
    except TypeError:
        try:
            world = from_lux_matrix(node.getTransform(True))
        except Exception:
            world = local
    return world, local




LOG_PATH = os.path.expanduser("~/Library/Logs/Perspective Studio Fisheye.log")
_DIAG = []


def start_diag():
    """Begin a fresh diagnostics log for this run."""
    del _DIAG[:]
    try:
        folder = os.path.dirname(LOG_PATH)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        open(LOG_PATH, "w").close()
    except Exception:
        pass


def diag(msg):
    """A line for the diagnostics log, written at once so it survives a KeyShot crash."""
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    _DIAG.append(line)
    try:
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def write_diag():
    """Rewrite the whole log (same lines as written along the way)."""
    try:
        with open(LOG_PATH, "w") as fh:
            fh.write("\n".join(_DIAG) + "\n")
    except Exception:
        pass


def _fmt(v):
    return "(%s)" % ", ".join("%.6g" % x for x in v)


def _describe(node):
    kinds = [k[2:] for k in ("isGroup", "isModel", "isModelSet", "isObject", "isHidden", "isDeleted") if _flag(node, k)]
    p = _parent(node)
    return "'%s' id=%s [%s] parent=%s" % (node.getName(), node.getID(), ",".join(kinds),
                                          ("'%s'" % p.getName()) if p is not None else None)


_COPY_NAME = re.compile(r"_sphere_\d{3,}$")
COPY_SOURCES = ["The models ticked below", "The Scene tree selection"]
PICKER_MAX = 40


def copy_candidates(root):
    """The scene's top-level models, groups and objects, for the copy picker."""
    out = []
    for n in _children(root):
        if is_camera(n) or _flag(n, "isDeleted") or _COPY_NAME.search(n.getName() or ""):
            continue
        out.append(n)
    return out


def pick_nodes_from_dialog(settings):
    """Resolve the checked model picker entries against KeyShot's live scene tree.

    KeyShot's input dialog can persist earlier checkbox answers. Match IDs
    against current nodes, rather than retaining stale Node objects across runs.
    """
    root = lux.getSceneTree()
    wanted = []
    for node in copy_candidates(root)[:PICKER_MAX]:
        key = "copy_model_%s" % node.getID()
        if settings.get(key, False):
            wanted.append(node.getID())
    return nodes_by_id(root, wanted)


def nodes_by_id(root, ids):
    """The live nodes with these IDs (compared as text), in the order given."""
    want = [str(i) for i in ids]
    found = {}
    for n in _walk(root):
        k = str(n.getID())
        if k in want and not _flag(n, "isDeleted"):
            found[k] = n
    return [found[k] for k in want if k in found]


def remove_copies(nodes):
    """Delete the copies this run pasted; returns how many went."""
    gone = 0
    for n in nodes:
        try:
            n.delete()
            gone += 1
        except Exception:
            pass
    diag("removed %d of %d copies" % (gone, len(nodes)))
    return gone


def is_camera(node):
    if _flag(node, "isCamera"):
        return True
    kind = _lux_const("NODE_TYPE_CAMERA")
    if kind is not None:
        try:
            return node.getKind() == kind
        except Exception:
            pass
    return False


def camera_free_pieces(node):
    """What to duplicate for this node: the node itself if nothing in it is a camera, otherwise
    the largest parts under it that hold no camera. KeyShot 2026 crashes when a script
    duplicates a group with a camera in it (KGroupNode::addCameraNode), as Rhino imports with
    named views have."""
    if is_camera(node) or _flag(node, "isDeleted"):
        return []
    if not any(is_camera(n) for n in _walk(node)):
        return [node]
    pieces = []
    for child in _children(node):
        pieces += camera_free_pieces(child)
    return pieces


def duplicate_node(node, amount, link_mats, wait=5.0):
    """Duplicate node `amount` times; returns the new top-level nodes. KeyShot may add the
    duplicates to the scene tree a moment later, so this waits up to `wait` seconds."""
    before = set(n.getID() for n in _walk(lux.getSceneTree()))
    diag("duplicating %s x%d" % (_describe(node), amount))
    try:
        res = node.duplicate(amount=amount, linkMats=link_mats)
    except TypeError:
        res = node.duplicate(amount, link_mats)
    diag("duplicate(amount=%d) returned %s" % (amount, ("%s of %d" % (type(res).__name__, len(res)))
                                                if isinstance(res, (list, tuple)) else repr(res)))
    if isinstance(res, (list, tuple)):
        got = [x for x in res if hasattr(x, "getID")]
    else:
        got = [res] if res is not None and hasattr(res, "getID") else []
    if len(got) == amount:
        return got
    t0 = time.time()
    while True:
        new = [n for n in _walk(lux.getSceneTree()) if n.getID() not in before and not _flag(n, "isDeleted")]
        new_ids = set(n.getID() for n in new)
        top = [n for n in new if _parent(n) is None or _parent(n).getID() not in new_ids]
        if len(top) >= amount or time.time() - t0 > wait:
            break
        time.sleep(0.1)
    diag("found %d new top-level nodes after %.1f s, e.g. %s"
         % (len(top), time.time() - t0, [_describe(n) for n in top[:3]]))
    try:
        top.sort(key=lambda n: n.getID())
    except Exception:
        pass
    return top


def fibonacci_sphere(n):
    """n unit vectors spread evenly over the sphere."""
    ga = math.pi * (3.0 - math.sqrt(5.0))
    pts = []
    for i in range(n):
        y = 1.0 - 2.0 * (i + 0.5) / n
        ring = math.sqrt(max(0.0, 1.0 - y * y))
        pts.append((math.cos(ga * i) * ring, y, math.sin(ga * i) * ring))
    return pts


PHI = (1.0 + math.sqrt(5.0)) / 2.0
SOLIDS = {4: "tetrahedron", 6: "cube", 8: "octahedron", 12: "dodecahedron", 20: "icosahedron",
          30: "rhombic triacontahedron", 32: "truncated icosahedron (soccer ball)"}
RELAX_MAX = 200  # above this many points the Fibonacci spiral is used as it is


def _icosahedron():
    """Vertices, edges (index pairs) and faces (index triples) of an icosahedron."""
    v = []
    for a in (1.0, -1.0):
        for b in (PHI, -PHI):
            v += [(0.0, a, b), (a, b, 0.0), (b, 0.0, a)]
    n = len(v)
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if abs(v_len(v_sub(v[i], v[j])) - 2.0) < 1e-9]
    es = set(edges)
    faces = [(i, j, k) for (i, j) in edges for k in range(j + 1, n) if (i, k) in es and (j, k) in es]
    return v, edges, faces


def solid_points(n):
    """Face centres (unit vectors) of a polyhedron with n identical or near-identical faces, or None."""
    if n == 4:
        pts = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    elif n == 6:
        pts = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    elif n == 8:
        pts = [(x, y, z) for x in (1, -1) for y in (1, -1) for z in (1, -1)]
    elif n in (12, 20, 30, 32):
        v, edges, faces = _icosahedron()
        centres = [v_add(v_add(v[i], v[j]), v[k]) for i, j, k in faces]
        pts = {12: v, 20: centres, 30: [v_add(v[i], v[j]) for i, j in edges], 32: v + centres}[n]
    else:
        return None
    return [v_unit(tuple(float(c) for c in p)) for p in pts]


def _energy(pts):
    e = 0.0
    n = len(pts)
    for i in range(n):
        xi, yi, zi = pts[i]
        for j in range(i + 1, n):
            dx, dy, dz = xi - pts[j][0], yi - pts[j][1], zi - pts[j][2]
            e += 1.0 / math.sqrt(dx * dx + dy * dy + dz * dz)
    return e


def relax_points(pts, max_iter=3000):
    """Let the points push each other apart (1/r, the Thomson problem) until they settle.
    They end up where the faces of a polyhedron with that many faces would be."""
    n = len(pts)
    if n < 3:
        return list(pts)
    pts = [tuple(p) for p in pts]
    e, step = _energy(pts), 0.5 / n
    for _ in range(max_iter):
        force = [[0.0, 0.0, 0.0] for _ in range(n)]
        for i in range(n):
            xi, yi, zi = pts[i]
            fi = force[i]
            for j in range(i + 1, n):
                dx, dy, dz = xi - pts[j][0], yi - pts[j][1], zi - pts[j][2]
                d2 = dx * dx + dy * dy + dz * dz
                k = 1.0 / (d2 * math.sqrt(d2))
                fi[0] += dx * k
                fi[1] += dy * k
                fi[2] += dz * k
                fj = force[j]
                fj[0] -= dx * k
                fj[1] -= dy * k
                fj[2] -= dz * k
        moved = []
        for p, f in zip(pts, force):
            along = dot(p, f)
            moved.append(v_unit((p[0] + step * (f[0] - along * p[0]), p[1] + step * (f[1] - along * p[1]),
                                 p[2] + step * (f[2] - along * p[2]))))
        e2 = _energy(moved)
        if e2 < e:
            done = e - e2 < 1e-11 * e
            pts, e, step = moved, e2, step * 1.25
            if done:
                break
        else:
            step *= 0.5
            if step < 1e-12:
                break
    return pts


def even_points(n):
    """n unit vectors spread evenly over the sphere, and how they were made."""
    if n <= 0:
        return [], "no points"
    if n == 1:
        return [(0.0, 0.0, 1.0)], "a single point"
    if n == 2:
        return [(0.0, 0.0, 1.0), (0.0, 0.0, -1.0)], "two opposite points"
    solid = solid_points(n)
    if solid:
        return solid, "on the faces of a %s" % SOLIDS[n]
    if n <= RELAX_MAX:
        return relax_points(fibonacci_sphere(n)), "spread evenly, like the faces of a %d-faced polyhedron" % n
    return fibonacci_sphere(n), "spread evenly on a Fibonacci spiral"


def _level_up(d):
    """World up made perpendicular to d (a horizontal reference if d is vertical)."""
    u = v_sub(WORLD_UP, v_scale(d, dot(WORLD_UP, d)))
    return norm(u) or v_unit(cross(d, (1.0, 0.0, 0.0)))


def orient_points(pts, d0, include_original):
    """Turn a layout to the scene; returns the copies' directions.
    With the original included, point 0 goes on the original and one of its nearest
    neighbours straight above it, so the pattern sits level around it. Otherwise one point
    goes straight up and the layout turns about the vertical to leave the original in a gap."""
    if not pts:
        return []
    if include_original:
        turn = m3_rotation_between(pts[0], d0)
        others = [v_unit(m3_apply(turn, p)) for p in pts[1:]]
        up = _level_up(d0)
        flat = [(p, norm(v_sub(p, v_scale(d0, dot(p, d0))))) for p in others]
        flat = [(p, q) for p, q in flat if q is not None]
        if flat:
            closest = max(dot(p, d0) for p, _ in flat)
            near = [(p, q) for p, q in flat if dot(p, d0) >= closest - 1e-6]
            q = max(near, key=lambda pq: dot(pq[1], up))[1]
            roll = m3_axis_angle(d0, math.atan2(dot(cross(q, up), d0), dot(q, up)))
            others = [v_unit(m3_apply(roll, p)) for p in others]
        return others
    if len(pts) == 1:
        return [v_scale(d0, -1.0)]  # one copy: opposite the original
    turn = m3_rotation_between(pts[0], WORLD_UP)
    pts = [v_unit(m3_apply(turn, p)) for p in pts]
    best, best_dot = None, 2.0
    for deg in range(360):
        r = m3_axis_angle(WORLD_UP, math.radians(deg))
        nearest = max(dot(m3_apply(r, p), d0) for p in pts)
        if nearest < best_dot - 1e-12:
            best, best_dot = r, nearest
    return [v_unit(m3_apply(best, p)) for p in pts]


def fisheye_directions(count, lens, bounds, cam_forward, cam_right, cam_up,
                       original_direction=None):
    """Sunflower pattern in the *projected lens image*, not equal solid angles.

    Every sample is inside the actual lens footprint. The extreme 180-degree pole
    is avoided, as it is a singular circle in a full-sphere projection.
    """
    xmin, xmax, ymin, ymax = bounds
    directions = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    n = max(1, int(count))
    for i in range(n):
        frac = (i + 0.5) / float(n)
        # Golden-angle spiral; allow for noncircular curvature by checking lens.unproj.
        a = i * golden
        radius = math.sqrt(frac)
        direction = None
        for shrink in range(32):
            r = radius * (0.975 ** shrink)
            px = (xmin + xmax) * 0.5 + math.cos(a) * r * (xmax - xmin) * 0.5
            py = (ymin + ymax) * 0.5 + math.sin(a) * r * (ymax - ymin) * 0.5
            direction = lens.unproj(px, py)
            if direction is not None:
                break
        if direction is None:
            direction = (0.0, 0.0, 1.0)
        x, y, z = direction
        directions.append(v_unit((cam_right[0]*x + cam_up[0]*y + cam_forward[0]*z,
                                  cam_right[1]*x + cam_up[1]*y + cam_forward[1]*z,
                                  cam_right[2]*x + cam_up[2]*y + cam_forward[2]*z)))
    if original_direction is not None and directions:
        # Reserve the image-space point nearest the original; the original is not moved.
        nearest = max(range(len(directions)), key=lambda i: dot(directions[i], original_direction))
        del directions[nearest]
    return directions


def sphere_moves(center, cam, count, orientation, include_original,
                 distribution="sphere", lens=None, bounds=None, basis=None):
    """(radius, [(world move matrix, target point)], layout) for `count` copies."""
    offset = v_sub(center, cam)
    radius = v_len(offset)
    d0 = v_scale(offset, 1.0 / radius)
    pts, layout = even_points(count + (1 if include_original else 0))
    sphere_dirs = orient_points(pts, d0, include_original)
    if distribution in ("fisheye", "hybrid") and lens is not None and bounds is not None and basis is not None:
        image_dirs = fisheye_directions(count + (1 if include_original else 0), lens, bounds,
                                        basis[0], basis[1], basis[2], d0 if include_original else None)
        if distribution == "fisheye":
            dirs = image_dirs
            layout = "distributed evenly in the projected fisheye image"
        else:
            # Retain most of the sphere's separation; use only a gentle image-space correction.
            # Avoids pushing too many objects into the compressed rear-pole circumference.
            mix = 0.20
            dirs = [v_unit(v_add(v_scale(a, 1.0 - mix), v_scale(b, mix)))
                    for a, b in zip(sphere_dirs, image_dirs)]
            layout = "balanced 3D sphere / fisheye distribution (20% image-space adjustment)"
    else:
        dirs = sphere_dirs
    frame0_t = m3_transpose(m3_look_frame(d0))
    to_cam, from_cam = m4_translate(v_scale(cam, -1.0)), m4_translate(cam)
    moves = []
    for d in dirs:
        target = v_add(cam, v_scale(d, radius))
        if orientation == "upright":
            move = m4_translate(v_sub(target, center))
        else:
            if orientation == "camera":
                rotation = m3_rotation_between(d0, d)
            elif orientation == "tangent":
                # Forward vector lies in the sphere tangent plane, pointing along
                # increasing azimuth. A stable fallback handles the poles.
                tangent = norm(cross(WORLD_UP, d))
                if tangent is None:
                    tangent = norm(cross((0.0, 0.0, 1.0), d)) or (1.0, 0.0, 0.0)
                rotation = m3_mul(m3_look_frame(tangent), frame0_t)
            else:  # projected: preserve original roll relative to the world up
                rotation = m3_mul(m3_look_frame(d), frame0_t)
            rot = m4_from_m3(rotation)
            move = m4_mul(from_cam, m4_mul(rot, to_cam))
        moves.append((move, target))
    return radius, moves, layout


def _close(a, b, tol):
    return v_len(v_sub(m4_translation(a), m4_translation(b))) <= tol


def _place_copy(copy, target_world, tol):
    """Give copy the world transform target_world. A relative applyTransform should act in
    the parent's space; the first copy checks that and switches to local space if not."""
    global _APPEND_MODE
    world, local = node_transforms(copy)
    delta = m4_mul(target_world, m4_inverse(world))
    if _APPEND_MODE in (None, "parent"):
        try:
            parent = m4_mul(world, m4_inverse(local))
            move = m4_mul(m4_inverse(parent), m4_mul(delta, parent))
        except ValueError:
            move = delta
    else:
        move = m4_mul(m4_inverse(world), target_world)
    copy.applyTransform(to_lux_matrix(move))
    if _APPEND_MODE is not None:
        return True
    now, _ = node_transforms(copy)
    if _close(now, target_world, tol):
        _APPEND_MODE = "parent"
        return True
    copy.applyTransform(to_lux_matrix(m4_mul(m4_inverse(now), target_world)))
    now, _ = node_transforms(copy)
    _APPEND_MODE = "local" if _close(now, target_world, tol) else "parent"
    return _APPEND_MODE == "local"


def _copy_orientation(v):
    idx = _pick(v, COPY_ORIENTS, 1)
    return ("upright", "projected", "camera", "tangent")[idx]


def _bbox(node):
    try:
        bb = node.getBoundingBox(world=True)
    except TypeError:
        bb = node.getBoundingBox(True)
    return vec(bb[0]), vec(bb[1])


def _landed(copies, moves, tol, wait=2.0):
    """Errors (box centre to target) of each copy, re-read for up to `wait` seconds while any
    is off, in case KeyShot updates the boxes a moment later."""
    t0 = time.time()
    while True:
        errs = [v_len(v_sub(world_bbox_center(c), target)) for c, (_, target) in zip(copies, moves)]
        if all(e <= tol for e in errs) or time.time() - t0 > wait:
            return errs
        time.sleep(0.1)


def make_sphere_copies(count, orientation, include_original=True, link_mats=True, log=print, targets=None,
                       made=None, distribution="sphere", lens=None, bounds=None, basis=None):
    """Paste copies of each target node (default: the Scene tree selection) on a sphere
    around the camera. Existing scene objects are never deleted by name. Every copy is
    checked; if they didn't land on the sphere this raises, so nothing gets rendered.
    Every copy made is added to `made` (even when this raises) so the caller can remove them.
    Returns summary lines."""
    global _MAT_LAYOUT, _APPEND_MODE
    if luxmath is None:
        raise RuntimeError("KeyShot's luxmath module isn't available")
    root = lux.getSceneTree()
    if targets is None:
        targets = selected_top_nodes(root)
        diag("selection: %s" % [_describe(n) for n in targets])
        if not targets:
            raise RuntimeError("Nothing is selected in the Scene tree. Select the model to copy, or tick it "
                               "under \"Models to paste\".")
    _MAT_LAYOUT, _APPEND_MODE = _detect_matrix_layout(), None
    count = max(1, min(COPY_MAX, int(count)))
    cam = vec(lux.getCameraPosition())
    try:
        cam_dist = float(lux.getCameraDistance())
    except Exception:
        cam_dist = None
    diag("matrix layout %s; camera at %s, distance to its look-at point %s" % (_MAT_LAYOUT, _fmt(cam), cam_dist))
    kind = orientation
    lines, failures = [], []
    for node in targets:
        name = node.getName()
        diag("copying %s" % _describe(node))
        pieces = camera_free_pieces(node)
        if not pieces:
            lines.append("'%s' is only cameras, so there was nothing to copy." % name)
            continue
        if pieces != [node]:
            lines.append("'%s' holds cameras, which KeyShot can't duplicate, so its %d camera-free parts were "
                         "copied instead." % (name, len(pieces)))
            diag("  camera-free parts: %s" % [_describe(x) for x in pieces[:20]])
        lo, hi = _bbox(node)
        center = v_scale(v_add(lo, hi), 0.5)
        radius = v_len(v_sub(center, cam))
        diag("  box %s - %s, centre %s, radius %.6g" % (_fmt(lo), _fmt(hi), _fmt(center), radius))
        if radius < 1e-6:
            lines.append("'%s' is at the camera, so it wasn't copied." % name)
            continue
        t_layout = time.time()
        radius, moves, layout = sphere_moves(center, cam, count, orientation, include_original,
                                           distribution, lens, bounds, basis)
        points = len(moves) + (1 if include_original else 0)
        diag("  layout: %d points %s (%.2f s)" % (points, layout, time.time() - t_layout))
        tol = max(1e-4, radius * 1e-5)
        spacing = radius * math.sqrt(4 * math.pi / max(1, points))
        copied, checked, bad, worst = 0, 0, 0, 0.0
        for piece in pieces:
            pname = piece.getName()
            world0, local0 = node_transforms(piece)
            plo, phi = _bbox(piece)
            pcenter = v_scale(v_add(plo, phi), 0.5)
            if piece is node or len(pieces) <= 3:
                diag("  '%s' world %s" % (pname, _fmt(sum(world0, []))))
                diag("  '%s' local %s" % (pname, _fmt(sum(local0, []))))
            copies = duplicate_node(piece, len(moves), link_mats)
            if made is not None:
                made.extend(copies)
            if not copies:
                failures.append("'%s': KeyShot didn't make any copies that the script could find." % pname)
                continue
            if len(copies) != len(moves):
                lines.append("'%s': asked KeyShot for %d copies and got %d." % (pname, len(moves), len(copies)))
            for i, (c, (move, target)) in enumerate(zip(copies, moves)):
                _place_copy(c, m4_mul(move, world0), tol)
                try:
                    c.setName("%s_sphere_%03d" % (pname, i + 1))
                except Exception:
                    pass
            # What the renderer sees: each copy's box centre must sit where the move takes this
            # part's centre. A turned copy's box can shift by up to half its diagonal.
            expected = [(move, m4_apply_point(move, pcenter)) for move, _ in moves]
            slack = 0.5 * v_len(v_sub(phi, plo)) if orientation != "upright" else 0.0
            check_tol = max(radius * 1e-4, min(slack + radius * 1e-4, 0.45 * spacing))
            errs = _landed(copies, expected, check_tol)
            for i, (c, e) in enumerate(zip(copies, errs)):
                if (i < 3 and (piece is node or len(pieces) <= 3)) or e > check_tol:
                    diag("  copy %d %s: box centre %s, expected %s, off by %.4g"
                         % (i + 1, _describe(c), _fmt(world_bbox_center(c)), _fmt(expected[i][1]), e))
            bad += sum(1 for e in errs if e > check_tol)
            checked += len(errs)
            worst = max([worst] + errs)
            copied = max(copied, min(len(copies), len(moves)))
        diag("  relative transforms compose in %s space" % _APPEND_MODE)
        if bad:
            failures.append("'%s': %d of %d copies didn't land on the sphere (worst %.4g off, radius %.4g)."
                            % (name, bad, checked, worst, radius))
        lines.append("'%s': %d %s copies on a sphere of radius %.4g around the camera; %d points %s%s."
                     % (name, copied, kind, radius, points, layout,
                        " (the original is one)" if include_original else ""))
    for line in lines + failures:
        log(line)
    if failures:
        raise RuntimeError("The copies didn't come out right, so nothing was rendered.\n" + "\n".join(failures))
    return lines


# ---------------------------------------------------------------- KeyShot
def _lux_const(name, default=None):
    return getattr(lux, name, default)


def save_camera():
    st = {"pos": vec(lux.getCameraPosition()), "dir": vec(lux.getCameraDirection()),
          "up": vec(lux.getCameraUp()), "lens": dict(lux.getCameraLens() or {})}
    for key, fn in (("dist", "getCameraDistance"), ("fov", "getCameraFieldOfView")):
        try:
            st[key] = getattr(lux, fn)()
        except Exception:
            st[key] = None
    return st


def restore_camera(st):
    lens = st["lens"]
    kind = lens.get("lens")
    try:
        if kind == _lux_const("CAMERA_TYPE_ORTHOGRAPHIC"):
            lux.setCameraOrthographic()
        elif kind == _lux_const("CAMERA_TYPE_PANORAMA"):
            lux.setCameraPanoramic(type=lens.get("mode", _lux_const("PANORAMA_TYPE_SPHERICAL")))
        elif kind == _lux_const("CAMERA_TYPE_SHIFT"):
            lux.setCameraShift(vertical=lens.get("vertical_shift", 0.0), horizontal=lens.get("horizontal_shift", 0.0))
        else:
            lux.setCameraPerspective()
        fov = lens.get("fov", st.get("fov"))
        if fov and kind in (_lux_const("CAMERA_TYPE_PERSPECTIVE"), _lux_const("CAMERA_TYPE_SHIFT"), None):
            lux.setCameraFieldOfView(fov)
    except Exception as e:
        print("Couldn't restore the lens settings: %s" % e)
    lux.setCameraDirection(st["dir"])
    lux.setCameraUp(st["up"])
    if st.get("dist"):
        lux.setCameraDistance(st["dist"])
    lux.setCameraPosition(st["pos"])


def aim_camera(pos, d, up, fov):
    lux.setCameraPerspective()
    lux.setCameraFieldOfView(fov)
    lux.setCameraDirection(d)
    lux.setCameraUp(up)
    lux.setCameraPosition(pos)


def render_faces(which, pos, f, r, u, N, T, folder, opts, log=print):
    """Render the faces in `which` from pos; returns {face: path}."""
    fov = 2 * math.degrees(math.atan(T))
    frames = face_frames(f, r, u)
    paths = {}
    for n, i in enumerate(which):
        d, up = frames[i]
        aim_camera(pos, d, up, fov)
        got = vec(lux.getCameraPosition())
        if max(abs(got[k] - pos[k]) for k in range(3)) > 1e-4 * (1 + max(abs(c) for c in pos)):
            log("Warning: the camera moved to %s instead of %s" % (got, pos))
        path = os.path.join(folder, "face_%s.png" % FACES[i])
        log("Rendering the %s face (%d of %d), %d x %d px" % (FACES[i], n + 1, len(which), N, N))
        started = time.monotonic()
        if opts is not None:
            lux.renderImage(path=path, width=N, height=N, opts=opts)
        else:
            lux.renderImage(path=path, width=N, height=N)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise RuntimeError("KeyShot returned without a completed image: %s" % path)
        log("Finished %s in %.1f seconds (%d bytes)." %
            (FACES[i], time.monotonic() - started, os.path.getsize(path)))
        paths[i] = path
    return paths


QUALITY_MODES = ["As in KeyShot's Render window", "Max samples", "Max time (per cube face)",
                 "Custom samples (advanced)"]
ENGINES = ["As in KeyShot", "CPU", "GPU"]
ALPHA_MODES = ["Transparent outside the lens", "Include alpha (transparent background too)",
               "No alpha (black outside the lens)"]


def _pick(v, items, default=0):
    """Index of a dialog item answer: KeyShot gives [index, text]; tests may pass either."""
    if isinstance(v, (list, tuple)) and v:
        v = v[0] if isinstance(v[0], int) else v[-1]
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v if 0 <= v < len(items) else default
    return items.index(v) if v in items else default


def apply_render_settings(opts, quality, samples, seconds, alpha):
    """Set the quality and alpha of the cube face renders on KeyShot's render options.
    0 leaves the Render window's setting alone. Returns notes for the summary."""
    if quality == 0 and alpha == 0:
        return []
    if opts is None:
        raise RuntimeError("Could not read render options; capture stopped rather than use an unknown render limit.")
    notes = []
    try:
        if quality == 1:
            opts.setMaxSamplesRendering(int(samples))
        elif quality == 2:
            opts.setMaxTimeRendering(int(seconds))
        elif quality == 3:
            opts.setAdvancedRendering(int(samples))
    except Exception as e:
        raise RuntimeError("KeyShot rejected the selected render limit; capture stopped: %s" % e) from e
    try:
        if alpha in (1, 2):
            opts.setOutputAlphaChannel(alpha == 1)
    except Exception as e:
        notes.append("Couldn't set the alpha channel: %s" % e)
    return notes


def switch_engine(choice):
    """Switch KeyShot to the CPU (1) or GPU (2) engine, keeping Product or Interior mode.
    Returns (engine to put back afterwards or None, note or None)."""
    if not choice:
        return None, None
    P, I = _lux_const("RENDER_ENGINE_PRODUCT", 0), _lux_const("RENDER_ENGINE_INTERIOR", 1)
    PG, IG = _lux_const("RENDER_ENGINE_PRODUCT_GPU", 3), _lux_const("RENDER_ENGINE_INTERIOR_GPU", 4)
    try:
        cur = lux.getRenderEngine()
        interior = cur in (I, IG)
        want = (IG if interior else PG) if choice == 2 else (I if interior else P)
        if want == cur:
            return None, None
        lux.setRenderEngine(want)
        return cur, None
    except Exception as e:
        return None, "Couldn't switch to the %s engine: %s" % (ENGINES[choice], e)


def _default_folder():
    """KeyShot's Renderings folder, where KeyShot saves its own images (the Desktop if it can't be found)."""
    for kind, sub in (("FOLDER_RENDERINGS", None), ("FOLDER_RESOURCE_ROOT", "Renderings")):
        try:
            root = lux.getKeyShotFolder(getattr(lux, kind))
            out = os.path.join(root, sub) if sub else root
            if out and os.path.isdir(out) and os.access(out, os.W_OK):
                return out
        except Exception:
            pass
    return os.path.expanduser("~/Desktop")


def _scene_name():
    try:
        info = lux.getSceneInfo()
        name = info.get("name") or os.path.splitext(os.path.basename(info.get("file", "")))[0]
        return name or "scene"
    except Exception:
        return "scene"


def _picker_values():
    """A checkbox for each top-level model in the scene, keyed by its node ID."""
    try:
        models = copy_candidates(lux.getSceneTree())
    except Exception:
        models = []
    if not models:
        return [(lux.DIALOG_LABEL, "    (no models found in the scene)")]
    values = [("copy_model_%s" % n.getID(), lux.DIALOG_CHECK, "    %s" % n.getName(), False)
              for n in models[:PICKER_MAX]]
    if len(models) > PICKER_MAX:
        values.append((lux.DIALOG_LABEL, "    ...and %d more: use the Scene tree selection for those"
                       % (len(models) - PICKER_MAX)))
    return values


def ticked_models(s):
    """IDs ticked in the copy picker."""
    return [k[len("copy_model_"):] for k, v in s.items() if k.startswith("copy_model_") and v]



import json
import base64
import webbrowser


def cube_output_folder():
    return _default_folder()


def cube_export_settings():
    return lux.getInputDialog(title=TITLE, desc="Capture six cube faces once; edit distortion and glass later in Fisheye Studio.", values=[
        ("folder", lux.DIALOG_FOLDER, "Project parent folder", cube_output_folder()),
        ("open_editor", lux.DIALOG_CHECK, "Open editor after capture", True),
        ("name", lux.DIALOG_TEXT, "Project name", _scene_name() + " cube"),
        ("face", lux.DIALOG_INTEGER, "Each cube face (px)", 2048, (256, 8192)),
        ("quality", lux.DIALOG_ITEM, "Stop rendering each face by", QUALITY_MODES[2], QUALITY_MODES),
        (lux.DIALOG_LABEL, "Only the limit for the selected mode applies. Preparation and file writing take additional time."),
        ("samples", lux.DIALOG_INTEGER, "Sample limit (Max samples / Custom samples only)", 256, (1, 100000)),
        ("seconds", lux.DIALOG_INTEGER, "Time limit per face (Max time only)", 20, (1, 604800)),
        ("engine", lux.DIALOG_ITEM, "Engine", ENGINES[0], ENGINES),
        ("transparent", lux.DIALOG_CHECK, "Transparent scene background", False),
        ("copies", lux.DIALOG_CHECK, "Temporarily arrange model copies around camera", False),
        ("copy_count", lux.DIALOG_INTEGER, "Copies per model", 15, (1, 200)),
        ("copy_orient", lux.DIALOG_ITEM, "Copy orientation", COPY_ORIENTS[2], COPY_ORIENTS),
        ("copy_include", lux.DIALOG_CHECK, "Include original in spacing", True),
        ("copy_source", lux.DIALOG_ITEM, "Copy source", COPY_SOURCES[0], COPY_SOURCES),
    ] + _picker_values(), id="cube_export_v2_timed")


def export_cube(settings=None):
    s = settings if settings is not None else cube_export_settings()
    if not s:
        return None
    if lux is None:
        raise RuntimeError("Run cube export.py inside KeyShot.")
    parent = s.get("folder") or cube_output_folder()
    name = re.sub(r'[^\w .-]', '_', s.get("name") or "cube capture").strip(' .') or "cube capture"
    # A unique directory prevents overwriting captures or partial exports.
    os.makedirs(parent, exist_ok=True)
    folder = tempfile.mkdtemp(prefix=name + " - ", dir=parent)
    def progress(message):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), message)
        print(line, flush=True)
        with open(os.path.join(folder, "capture-progress.txt"), "a") as fh:
            fh.write(line + "\n")

    with open(os.path.join(folder, "capture-settings.json"), "w") as fh:
        json.dump(s, fh, indent=2, default=str)
    progress("Capture started. Settings recorded in capture-settings.json.")
    n = max(256, min(8192, int(s.get("face", 2048))))
    tangent = 1.0 + 4.0 / n
    cam = save_camera()
    f, r, u = camera_basis(cam["dir"], cam["up"], False, False)
    made, notes = [], []
    prev_engine = None
    complete = False
    try:
        if s.get("copies", False):
            targets = None
            if _pick(s.get("copy_source", 0), COPY_SOURCES) == 0:
                targets = pick_nodes_from_dialog(s)
                if not targets:
                    raise RuntimeError("Tick at least one model, or choose Scene tree selection.")
            make_sphere_copies(s.get("copy_count", 15), _copy_orientation(s.get("copy_orient", 2)),
                               bool(s.get("copy_include", True)), targets=targets, made=made,
                               distribution="sphere", basis=(f, r, u))
        opts = lux.getRenderOptions()
        quality = _pick(s.get("quality", 2), QUALITY_MODES, default=2)
        progress("Selected mode: %s; %s" % (QUALITY_MODES[quality],
                 ("%s seconds per face; sample count ignored" % s.get("seconds", 20)) if quality == 2
                 else ("%s samples per face; time limit ignored" % s.get("samples", 256)) if quality in (1, 3)
                 else "using KeyShot Render window settings; dialog time and sample limits ignored"))
        notes += apply_render_settings(opts, quality, s.get("samples", 256), s.get("seconds", 20),
                                       1 if s.get("transparent") else 2)
        progress("Render options accepted by KeyShot: %s" % opts.getDict())
        prev_engine, note = switch_engine(_pick(s.get("engine", 0), ENGINES))
        if note:
            notes.append(note)
        paths = render_faces(range(6), cam["pos"], f, r, u, n, tangent, folder, opts, log=progress)
        metadata = {"schema": "fisheye-cube-project", "version": 1, "name": name,
                    "faceSize": n, "tangent": tangent,
                    "faces": {FACES[i]: os.path.basename(p) for i, p in paths.items()},
                    "camera": {"position": cam["pos"], "forward": f, "right": r, "up": u},
                    "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "notes": notes}
        with open(os.path.join(folder, "project.json"), "w") as fh:
            json.dump(metadata, fh, indent=2)
        editor = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor.html") if '__file__' in globals() else None
        if editor and os.path.isfile(editor):
            shutil.copyfile(editor, os.path.join(folder, "editor.html"))
        else:
            with open(os.path.join(folder, "editor.html"), "wb") as fh:
                fh.write(zlib.decompress(base64.b64decode(EDITOR_HTML_ZLIB_BASE64)))
        # Keep the editor's relative download link usable in portable captures.
        script_source = globals().get('__file__')
        if script_source and os.path.isfile(script_source):
            shutil.copyfile(script_source, os.path.join(folder, "cube export.py"))
        else:
            editor_path = os.path.join(folder, "editor.html")
            with open(editor_path, encoding="utf-8") as fh:
                editor_text = fh.read()
            editor_text = editor_text.replace('class="download-button" href=', 'class="download-button" hidden style="display:none" href=')
            with open(editor_path, "w", encoding="utf-8") as fh:
                fh.write(editor_text)
        complete = True
        progress("All six faces complete.")
    except BaseException as exc:
        progress("Capture interrupted or failed: %s: %s" % (type(exc).__name__, exc))
        raise
    finally:
        # Keep cleanup independent: a failed camera restore must not skip engine or copies.
        try:
            restore_camera(cam)
        except Exception as e:
            notes.append("Camera restoration failed: %s" % e)
        try:
            if prev_engine is not None:
                lux.setRenderEngine(prev_engine)
        except Exception as e:
            notes.append("Engine restoration failed: %s" % e)
        try:
            if made:
                gone = remove_copies(made)
                if gone != len(made):
                    notes.append("Could not remove %d temporary copies." % (len(made) - gone))
        finally:
            with open(os.path.join(folder, "capture-status.txt"), "w") as fh:
                fh.write(("Complete" if complete else "Incomplete — do not use this capture") + "\n" + "\n".join(notes))
    message = "Saved all six cube faces to:\n%s\n\nOpen editor.html, then choose this capture folder.\n%s" % (folder, "\n".join(notes))
    progress("Cleanup finished. " + " | ".join(notes))
    print(message)
    if s.get("open_editor", True):
        try:
            from pathlib import Path
            webbrowser.open(Path(os.path.join(folder, "editor.html")).as_uri())
        except Exception as exc:
            print("Open editor.html manually: %s" % exc)
    lux.getMessageBox(message, title=TITLE)
    return folder























# BEGIN EMBEDDED EDITOR
EDITOR_HTML_ZLIB_BASE64 = (
    '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'
)
# END EMBEDDED EDITOR

if lux is not None and not os.environ.get("PS_FISHEYE_IMPORT_ONLY"):
    try:
        export_cube()
    except Exception as exc:
        traceback.print_exc()
        lux.getMessageBox("Cube export failed: %s\nAny completed faces remain in the new capture folder." % exc,
                          title=TITLE, type=lux.MESSAGE_BOX_CRITICAL)
