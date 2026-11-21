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
    'eNrEvdtyG0mSKPiur0ixqoVMIJG4kRQIMMGlJKqk05KKI6q6uofDkRJAgkgRQKIyEyRRJM3maeys2bF9OHtse88P7PO8nYd96/6T'
    '+pL1S0Rk5AUk1d1j2zMlIuMeHu4e7h4eHvtPx+EoWS99Y5rMZ4Mn+/jHmHmLc3fLX2xhgu+NB08MY3/uJ54xmnpR7Cfu1iqZ1Ltb'
    'acbCm/vu1mXgXy3DKNkyRuEi8RdQ8CoYJ1N37F8GI79OH7YRLIIk8Gb1eOTNfLfFzSRBMvMHr4N46q994yRZjYPQ+O3f/gf89BZj'
    'bxYufOPHZRJAHeNocR4s/P0G18HacbLmX4bRi8IwMW7otwEDmYUR9DT1537PGHvRRV/k1OvD857xXavV2m6108Slt/BnmP68NWzt'
    '5dLr/sy/9BJ/jAUm7Z12Ky0wgyFBcnvY6bTHafJ8xcW7/t5or5mmJ/51Asm+P+n4wzTZG40AbpAx3pns7O3mM+rns/CqZ0TnQ89s'
    'tzq20d7esY3WTtM2mk5rx0rLhxGsIg5osuP5zzuccUf/Vo0bYxhe1+Pg12ABMBiG0diP6pDUN+ZeBLDtGc2+sfTGY8qH31xxGI7X'
    'CrJDb3RxHoWrBczu0otMhKfqn8Au03GqKmcS4vRaneW1UfeWy5lfj9dx4s9t4wVA8OK9Nzqh79dQzja2Tvzz0Dd+ertlGx/DYZiE'
    'thF7i7ge+1EwkW3Og0V96gfnU2y52bycyozw0o8mALH6dc+YBuOxv9DhMFwlSbiABmFVRwni5XIFf5xxeLWYhd64zgUAWjzoYDGF'
    'XpP+hurFeiWQ+g6QZtx+LgfIoIdRAzjicBaMje86o+1uZ/IwIMWqRd44WMU94/nyWuaohetCq612mjFaRTG2tgwDIM9IJieAKjGQ'
    'ZAjr7s1mgEntuAin3hShWZwmpyNK6dPstDvjzk5fjlJM47ud9m5nZ1dCsATSOMX62B8B+vKAFkD4fWMcxMuZt8Y1QDqrT2Y+IKs3'
    'C84X9QCwBQCA5AFz2tB0bxKOVnH9MoiD4cyHjsJVwhTbVqBnIDOhWX1Zoh5OJsDzegagbHbpezAqD1obY3NLbxQkMMCmg9OWkB77'
    'E281y6GMs4wCoLP7SEkOIosF37V22u1WM4cBGRTJVUTErV8J0tjdaRaXVQ5GLaM2k73cuL1RElz66bAf7v++vCxZjDrddrtkePEc'
    'UfImReodWK89XAqaG/AwWMNWi9eGKuKWhTMR3UjGsNtNCUGhE+GRSCzDJpH1dRUnwWRdF9taz4gBSH596CdXvuQpGt01gS2nnSn2'
    'CvOZ66TOUEEcK4UJMfnWc+DxwN1bXeTw3Z1MyXEULuuTYJYgCxnOVpGJ1K6KLENJ1TD60cVa0Xu4RKYuvn6tB4uxf02cU6ade1Ci'
    'tSvnIEhqCHwCcT0LvXIq5BbaKck4s/A8VItCkgCQlMac5DrpaYo9OjsbqLScGe40f5fmwEY39ca4bQYLIGSjDvOCJWpu2EW3rQKW'
    'nEeB2tEhBVa+FEseJESBrN1SuE5bYqORxRD8xsxPoIc64huhVh34yzK7T4tWQGwaRuGV5KHE1CdhBBi3Wi79aOTFfrE5AmyGlIi0'
    'MjMhCcZS/SATCBdxEQ9oyXFum/gy178KowsiH4UMpXDG37DhzSEn8ZHHrOYLaA22+rl3bW43m8trWLJJZBmd7WaKMbooAKLiyCR5'
    'wKgT+Vs62OdegBsOVhDYqMs8bWiTqTg/Tfy3Pg4if8S0xUOT4OE5LqPwK+QjaRdnqfOcxzGWezgT40HKXPI0q49k2sb5SsSB/9vO'
    's9GuSlB7BjCFMiTc1ig7Xg0T2lNL0UZvX+cHQ298nkJHL6Ut52ZUFgUKCF0iBskdY7PMte3tjLZbG5hJWxvPY/ezctbS7KrCV1NY'
    'Thq2jzLOVeQt5boxeJIwnA296H70+bu3LEWzG9CpnUMnHBXy0HLi391I/EQ0OMmeQVPNUEuceDomzGgzKiPodrdZ3C+226m8D6xB'
    'Fd7R140bJVmybLVgpUEfPce/MGDTn82CZewbXiImYIOAst0etXfhR9NvgQxmPN/5nbUZo8q29ixW6XJ5ulFHPrA7kLH+YYJKNlvq'
    'Q2XaEC+DM468cynQ3yPfZfZV5CXEMPUypKqm2wbaBlCMK06VVk2wYODWv+tnlpFTknA1mta9ka4T6A2PvMWll9mThrNwdNE3Mu1m'
    '2+T63+FkoUZmbN4QlhH4V59FBtoapEg/isIYJh6kqgYBrj7zhv5MYXFJW7r01dLkw5k/SXTObeS3402sjvbunIaw1/ba3VRYYUWv'
    '7l/CgsRZAqBOJt48mAG05uEiJAZRxAhY/2ihydObZ6a4hja5SEB8tzjU55O95nOvf/8G8LfPIMUONEnVJ2GY+NE/YjdORdvsRlPn'
    'lW1v2C3Eflgy3VaOyQLYk1Wship4MrfeLMWSVqsI3uHO6LmnMIE0WYX/zs63YQEMx/GjKIzSTf67yWTP7z5Xcp0XB+OCaihQ+7Ea'
    'D2eTpc0q7OI6O9cZxCYpT7P+wNS8VRLqs4pZfMsP+FFKmlxvVfieDTQn64tuezMvTuqjaTAbKz6ryfLTTm7xmcXqdLVh8b9dXnJK'
    'KHPkjXdHOxkkQJKIwpkSINMZamYRWSo7vVyFVGPJcsz/HAEn13k5ky2h2e9Ge+PtHAx4vOEqWa6SvLSr9kVqFtICD/4uVnM/CkY9'
    'I/GGq5kXYUJcarnADsj+eIrmeJeMt2fQSWb/EhtreceKuEk0l7uVf1WPfOyqRGVkw2W+k6z1sFk6PJjG0I/Oyi2czUmrkzdS3WPh'
    'zKvuJQI8KuzdDWw1YxMVE9lrZqlOG/lo6o8uQHZB2N4LTrHmrFE/2uLR1YgBqjrxMvI9JIIHsFUpRcmijoBcbpCwt1PdnzeEXV2j'
    'UpVTw7UQprPKUHeD+YyHDcVysya9fJNGvo2rA4q4QWr4Q1YAiYSIWIiJD41CURtxNmqyx0JF37h34ZbBApY5b5YGzOy2tvulWNnd'
    '3uk875fZ1VPosQZb2JFznS5zejaXKerVmVqnLJKf6YDPCLqwd4SLMdmNH9a0CZaFTV8Zx4PLgGykivSxuCpJy1fcmHkT1Gamq/OL'
    'MAk0m07+zMNvNx/QvzvPN3CE3UecbOQ3pe0H+Xy5QJSZzEMrMvYTL5jFRryaz8Wy5A5YiktSunAZRtfMN7/M2QXLlnZ3Q8slrILa'
    '/t/mPqi8hqmpXntoUrM0szlb0RVWkASVUcd3mY/kVfsMsQgz5p1oVbMebjAJZC2Em5gO8Ju0ghA9M1Ihr1NGDG2qbybcUhEvHYWw'
    'Sqj57+C5osjGf4U1dBHM6aSKxdZU3ME+mJAkPBgSGmFkxF1JFhuGlaWJjCEtPwSUHgWNNvsbyvC+hrxa8Ca1GLQWG2qVSQCMPV0k'
    'uA21pJiR4hoJGoXSk8CfjeOU6CTN0VJuKJ2Wok2SJoSwyc1HgAPZAqCBvjH5i/HGtoV8mukhZ/0Vxl/sF1eXaTBDginlEuFKO1ow'
    '94mE4xHIy9CJdlJNhKZjUbtYD6Cp7NY7tPEqtTy1q+h6aXu7pPNoNUMSV1WVQo81mn0im2afVfhmPwOHvDyTFWc2wIGQTdMy5cnF'
    'ZALgRLVldGHcCHpDsaJkUlk9rZxYNBKL/KUPFQEImAUCuLLx7TXH/rlNqtLSiyDFaGa+hFr5O1AqoRfLBn0X/9fs3pMDiVZuUqNZ'
    'sNwEYRR1xWw7uDzpkhLj0KbxXWd7u9Ue9Qs84rvnre7eTrefZQ/YcMZiRiQkNieAwDC7ljo9CDmtOAmHyRgPu/WBbe/tDGHnzpgK'
    'swJZtil0FAJ4CJa4I7dx3RwurOHKVilMlSQAqkQ20QZxnr5y9iKddyRRMK9PvcUYzyo24TzDfy9dGeJVAnSpMlWErg4U9t3pdEp6'
    'xm0lAmYoaCu7btviYJJoNVPLx4NXSYjZSlTcYM6WhfU8GBM4ymZL/eMxKU9b0JNqm7IRzcZePIU1l+5I94FXchVErClpPeVAJkOO'
    '6pAB3s7iO2MQuzBZpZ3KU+u26P47xb1PRtFqKPclWj3J/dsajNLyR/Nlsk5Rss2KSQkH27C9lfmX2Drl5F1PpOfJJseTnN9JRzFu'
    'Fto0me05iWw3JbsibkjAQ+6K8omSRqD7O2x3vyGc5/Yb7Oy3j25eA5QT91kIZL+6fVAajNHMi2N3i06stwZCVNJz8JR/a/Dbn//3'
    '/Qak6iXkb2y2lXP0g65bWr7WnjjV3hpoboAvgeSDxSpcxcZHb13wCtT7TT/0n1r7Qh5N5+LJnJwD0ZYxjfyJuzVaDf3ftZv+NVqV'
    'neV6y5AFOc/Qcsg/0d16JQoY2XzbCOb40wjg/xfG7/31yTRMfvu3/xkbgMPBErct0M8W0L5tJFN/YUSrBRZOQtiDlskq8o11uIq4'
    '2QmwztgB0P/7/2moDkWbRkzt7Tc8NU1hIQhg1OHSX7wOZ7DQW3Luwidoa/Aj5In2qcR+gyuWtYM9Ho2DZGvwDvsGXE3i+8rH3qXP'
    '5U/gV1l5tWaMmoiJ+EFiKDXBg3qL3wBtlEu3JsHM3zKu/OFFkLCcFoJqNl/NkmAJ1MebySDbDHZd0ggS5DJxt5yvcbiw0VkR8AzR'
    'pYEJW6qtJ1mUUuqLQKp99DQooxXtbH4ri/3pF1JLmwYpSn+ADXRr8BYZonDH6rwyXvnzEJDGR/SftjO1tf74nH5Lb+096Jhbg+Mo'
    'HPnjVQRE1OrALjz1AbU+TcM5TBOkYECyxPjL/zJoWT2FVBIHAR0RgIyLgHkGyE+EKlmiz30ChBaKnaArAI8rhkZG/gtKGPzsD394'
    'Z7SNdzBNYFNQI0fYOlCxNuvtCo3lp1iokkqioDhs3yrnQeLQeysDV4HIErTkpcYLwhPBSh+BgmPkhv8H8izk7lEwMig1Txib2kwb'
    'Ow6QTf323/4vWAdkd/hd2ooOWWHo2RpkwXd/b7ADh4p5/QQfhvnbf/u/Gy+TaGb8s7U1wKRvG3/kay1+9DMtnkyDSULtYkax3Tzi'
    '/A0Lw4NgUQpg+AbNBeLr2+YxCueoHqipHIM4GBvPjCnwIaSD4XoJVYS1aOTPYcWhO8wMQXgLFt7sgfltRlEyRwgaoZ/lINHOorcG'
    'L3/88Onth59+/OnE+Hj4J+Poww9vPxwRJb/9w5Hxw/FP98AWD065O/qVgY84beeVXQj84sRN5cQpOzDVKPB4fO6WzsUmQiCQB7aO'
    '8Sryzg20A8cAPRhWANohwJggaywB+52ybu+Zkn6cLbmgj/29XUxAaAFZsWmATCYSH7kuuQPmrTyLk+T7JkBcoDl5NCvhdTJb9w30'
    'uYCNHeeJEi/gjwdKMmFUFCZe4uP2D9IC+mfkCTnthZeC53ICHcxAFEdsHKXiUgTi0moheD9sZKVMVbYrTkiloJQVJLMLeSgzDakF'
    'bEBPNDvxmQis3bQzUBVh3+oM9qm5gdiZeSuWBza8YGoU78JwCXweM/3xwMDP/Yao/jDDMEjkdbdyVpZSRpLp9phwOC8lYWqKNoLA'
    'S+ufQFcoy+JoNzOeTJUXXuwjb0S3q0If4ngkU+ETLIFcHqAsoL3JZGvQdAC7G8Y2/gGuxxU3k81SEY08dSgFWhOBdjgGsWBheGM0'
    'CiHPM4DoIYF1IEHIHnvkIE7PgRkYeI+C8N4PALkjECHOSZQYTYkEkBpQIsEJOcYJmxA9hV6iMfSbXRIPfgUlgE6AUbwANZKtx0g+'
    'vujMgR14uSY6UoYMHh+I2MnUkNtR7SU36sUJUhxpXIk/WxveBN1HgnzxPzjGRyRRxP1Lb7byYeYgE6U0h+ckv/37fzc6u00jAAqH'
    'sU9WICuA6LSwRd7zNuUlVyGQ97IcdfM63paklkMF9n1hac1gwxFNkgQAyh0oMilDNljKrUHNwBVl6NyPzsfeAovD3P7yHwCzxf2l'
    'cQW2DHVpQuyhtC75NTHT9QDBgIo8bjywbMUuKFms4ChcBmX9/AH64XL5jjazk8KaZEfzdhEvSf/Y0tQO1Q6vwusonOuaCPWNiVIV'
    'YUM7Ep+/xLbXW+kK8p9PYaGBT+EjqhcHc0K2KTO2Cg1STr7NebBwt5qy7abTKgztlaDg0jZlZnmz0FpZw8VBH3kxbHY67nPznA41'
    'w2VKnaClkh0YdFT6C4yQcvOl4jns5lPg1PQ3LVUgIj4jUJKtN5oSjyESFzg29WaTKw95TxSuzqdSl/dBIop9Og9CTkWcCaGMogGN'
    'AoZOu/NHH3kFlqF8sWcXwMnFtvLb5v30/pH4Y2qpYC5aoEaR3kiZK1CLSMyRy8YdJR1v1lQnR0yiT4pUc+/a3dpOcaAJ+CAWp7lJ'
    '+JCWx016XPbQBUAj9cbM3kniS75OWeGPeHxSKMmnKluCb5R0gccc8eb8YzmJQsPp9ERd7V99587yfzRvbg0+hGKhYmPtw25Ie3bK'
    'uBV25TagbxEDFCv9ZwM1SNgJY77Fixuq2rjJzNNPN1BS/6AKqohQBchg7hgIAyIMGlNsTIAhEoWMVhGdzpApXJ0vJkg0sWN8YHcr'
    'NVMPJgm1gkhKFean0Pjtv/53AxmsZaC4Gi5BulDmJyNYjGarMYyDjBly0DAgFrygCsrrxx9+EGY8YxXzoHGkCXYNzRAFQ2nH+JG0'
    'nuUSUxZlgwvPfZR+HOOdv4jr83AM80FwhYsGSG2qbAxCB3AWNVNtkZAlkaA+yBtD2G9zS9N+8HPAZlIDZfA14AHwqVAYUFE7wMOt'
    '1czjQ3qosiYoTUE6mQNvQ1hkbKps2uKPp/W6cQKqNd5aeMmOgLFRr4uidEivxkhlhYLR6gF4pUaiKqQaiG447gyaLWBD0uR7rGky'
    'kFdK9cIncau4dSibNWnLxiSMAKthCWBzgNUw3uNqlO072lbDxbVMyM7uJP4vq4Cs/FuKrQ6OZBrq4sfTENAg8pZTQA7q2PwQXFyE'
    'UeMkOJ97ltp87usFuGTky1ZQwdA+sRNYD3QIBZAdMphfenPDfAmktIrWxvvftx7XDU4GhKvEQ132KP3ALl6Fc994jxJUZJhAwAsf'
    'aDdYzR/XMtDSNB3/j9oXwQiaA6x6488Dsk7i4j+q2e0lDHS7zsdg0FCriwxPHj6Yx7AFo4iGBgg+iXjcaHew2Z202T/gfoSHOy/R'
    'zgFq+qNa2cVWdtNWfp6G0MQJm19N5s3pWcfjRgYsEdR/UXcNzGscMaVAeuTNvbJGlFRzrxFFsxqTLM8EvjXI2UkU0ZaRertnvNJs'
    'Y/cT+wazQcY03snuRr0mKLptYBDaEZHeYZZL3G+xBGb7sxcther9sHzz4FbZ43un5HCTmcYJaPYkOaJZiM5/hqDzwyzYGG7wQa8x'
    'CaI4EdIjqcd+DHNkyYeLCFVbmqSE8YzUYDy11mvEQvvOWpyocHIFRC02YrJVoxaNlyXpaNgnsxQaInAB8QAGumUx0ljgkfkwZOsW'
    '1QSmA+o+HhJEsMnOHA16upihi6bjMXa6lV0ToZNio6liJrESUzfgo4a7V7CY95cqItsGWSe7fKkFDvb5l+FqkWwVUWGAxpdWm+yW'
    'm23xZGOegV5Cxv4cCF5ihmjgMUZyMSKynUmLlfgsUUeXsvwnVAVAF4YFb2VWKdvsRlA+inKV9qapBdDouxDNeUUdBo88LgCA3mI0'
    'DQkGJftyFoxj0k5gFnkwstpSan6758TqAcbW6bFMgocBh6DFRkKC+k9hcB0pAeV6K3C3jHJ6tKAdCpsDXjA2zrFnwITz6QyFaVzI'
    'dC0ok2sUlyM1u/5AbbxRbRRW5R/HJI+n65h2MlSt65MI/YjYgg7DAXGepG88eIEtPcCwLFKqvQzOFyw32yRazwKUW8T0I38y43WJ'
    'N/EmifPU3sNshtrNFyuso/LJE7JmvIrwAF8fD1vESwA2eB1cMxdGvYPncTUNZnxKEOMpMJlYgS//BNvIR9UkTP8cSiEQtMQ4nCQL'
    'NKF6Q+ThqAhOvSU3RqsKkHMKK234hByk+8Rs78QJk2aiYDGDqZ3wzP42eWG7ZxyxnvWgWrANRCGkTxE8imtuVgw20RxTDWkDrOT9'
    'jM42IJSyrZ2+DHN5bZXpBppVRqtbZuFqN6WVo9N+vtuVlo4WJgthrrXbhK9HnW2pux9bj5Zv2hdbg/bvDbPd3O5a33qeG29D7W2o'
    '3eluN7+99i7U3oXaOMFvr92F2l2o3W3tta1vOjHWwHRvDy0cYGvX5iPBgtG5HJ5NBGizUIc5wFJzb3hFnv1lUgKRz1LDn1cByK0x'
    'uSg9yhSzS3yTONi92vCGE7D+I9VkHtzJyeFhbls/BLm7fjgLyPhqmFjCyukr6ZFVHHveOz6qbv/1z23D3P7rn63i2RSu6L1a+MbR'
    '5JSjFqzpX/+MqhZ7k0Vjw3wNPEMYcx6nYbU1RZ5Gjf1im8gcjX9aebMgWdNU+GQIWPUPUTB+XOMd0N3++ueOalOwsp9mID8b5h60'
    'ebIaLoH/z6xv0uS+TdBF10GjeR8u6CibsrxhMFrBf68pIhEJ8Rslh5MpiON0qQtdiGJvvpwRwrzgJqwHJYlHCezSTfwBzC6fjeYN'
    'fs9EPmk+44C4dBUF9z3QVeabJlGq+DAOHn/4oXC+LCelubQqL06Wk8QmKfY/NE/+9u9/Lj0qG4EI7c+4vNQD8noGFRE0kXJXDfTy'
    '3lORhWwXlSO+HDU4HKIXGVkSfbZAPjPCyWTGtkj0XCDdThbPqCZZkvmkteEj3QCNxWgZvgRSi7y17vEwWxsgENaJYowV8SThVOYY'
    'r0GTiAEeZFtHjXtcHBAJS63d+jBIEKyNT29fv5Z3Eof+OqRcwfFt8s/cH4Vjf7BcJ9Nw0RFA/IxSNuwQznJtPJslfeE595ndF5+d'
    'J/39BlVDP1C2PPvRHN2FnAxxLzOYxKuwwQ6831AGV4l0++wFOnjSqBL5+WMb75hRTwFGCIPe+UxKyNWoMTvGCyCvGLCKzNICPgBw'
    'EAFXsRA5URa/WKBLYLhAswCd2VcbT8zJakFjMjEmp3XzpIJVYvSCSyr9J1AaeC8g33zpmpe2Zw8td/DeS6YOhnjybP4ZLMyhfWlZ'
    '/SeyNRlVj4wTpnUT8QHZqdPu2s7Oju1022fQxNKM3IF5w1tuL7ITwFM/gR+ROLDvNe8sdOtW7QIyBWPAJm6YLBgwaCOYmE8PQcla'
    'O0FMf0XW7S39dYDcz5PpoGvhCd+VcYSBEszKTxxAZh7i/oIyM5tEnAreVgYV1PDcpj108VqkmADni4HfwD5rMoQuAO7GaYUnUrEr'
    'PBH4ISdSObNwjB9IvIRBvsYIq74ZnV6cWdlBvV3QHNkBqVK7wLFA1cjhxvddr+YANjdbMDeH+9l3h1oalxu4WgH4yHbyUXo3BcZ8'
    'BePPmY+CBTFJ0i+AUSJAPFe23B+6st0UMGoNRSG1lKJkuqKETDAdmWDXn4NEBv9Zd/07mKy22PEsXPqxeW2vcY0Z0gv3WqymPXVP'
    'z+wx/jN3F/6VwQu/QIDhyuACfoXF+7q/qLf6X2s162Z6+vXMvT79Wmud1eHPWX+MCeaaU+DPmdXAMujNDzBfuK7btiTujk+b0B38'
    'c5bpoKV3ALQM9aDVeuusio3vu01rjp3Q3Vp/Bhh3wxO5arntKnZWm1Jx+6rt0ielQkKf6plXrdpV22rA3wa3C5/464yuO8D/K3AB'
    'RyRDtTlt2tOWPW7a45Z1g6O8dE0Tmm3Wpi2rOm7Wp80qZDVMTunDkC8hGcd6CQOlUeI0sNR+89kzonJvGJuX1kD97kANC8rj376A'
    '0SUOaQ4gctOxINSmpy0GHfzTgoHPTwFimUKLehuLLeodLENfY/qyZNvzDGrQXpLSfxlb6EuUuXZPm7bjOBnilYhp2TC0dXkJRmUs'
    'odry3FMqBHM5UCh8e1tWW+ZaNmd4iVlvWZlazAMv3cFlleB6/LbR6jYtjawA94HrznsaKdie9ukB1ehwgU5GdoQgiVxBaXbThjWW'
    '1EBmCPPr/siRdFRvP3sWDeCbqMACPFaznboyuU4/zuzENSPxG0jFTtpuUk3spOMm7Wqi6sk9H0jLnsOOAciXdOqdatKuAQIindVM'
    'SGhjQmJVp9U5JWFCp4bFqBB0S8Xwk4rUaCEkPcpOzJGztkfO3LK1FA9SvLl1lgEOmlwQQxhB7K+CScH2REv69UzghICc4FymyAWM'
    'PRAFYOks5Li7KrOmZ7asOmYq1M013y8Z0gmhmhqYwDzBKmahq4+BMxHppoGr9y8zWva5t3TV3swDnQb1WWg1OjAqORwuL2Yr+PYs'
    'rEFlaLkOf4ozEFuAjnF8GpDZizObrtuVLBS4pBAoXJ1+CTdxxPWWTVfGiFlmWbiGrsxqoZccbg5wwHitKo+0fW70KzIn7l8sM7VA'
    'mWc19RNpoNG2TwU8yCB35hJdCXRBHKQJxnjdxDepGlDZTWbrS3c8aqIKhN0QRH6n4EpVEUcFd1kG7o0uOtkZxmYz2dsEPNtLbIk9'
    'dhaNbLEmwBoATKgXgXQyD8ermf/UdSsr6HQCMuK4YnGiwzJw7EL/zP1RGHTwbA1HTMlP7izZ0vksHHozlPGzrR2kGT3UIgBQT0Dm'
    'FSKtLtu+XYwiOu3DY0/01FigbB31yPcynqKiJMV+Y4hSLcgmc38eRmvbWIRsX6bjMnYtf7wkm6BFlISFn2Df6bRZZGjv7OLtZ8a3'
    'BeDbYh+S+gvc0TFp5C5U9gVkX+x3+xeQCWj8rHXQvPbHw263027+qzkaDAYtq0d/+tTZ6eLMxc+mTjOj6WpxQeC0YXE9Seegtaix'
    'dXlomC0Qv9ZqW/b4kkq8guQ/BP6VCVWc4Woy8SOrP750Yj/hiZlNW6uazo6paZtICOqebtdAxsCBOPhwwEtYhcPE/Eo3HLEx6t/u'
    'MomOopHbvJ6I/2lNQnNoM5IEyq1jaYaACT//FTuDPeNZe2fn7F8xBWDSzY1Zb8OmWml3FsJQ0Q2UBHiSUowIdJJEvjcH3iNcfLx4'
    'vRjBeH3cDPhJA74rbIN+eSHFNIHOL8M5OSiT7ze242ZpJCM4cwmUnhFvI/S2iNCh2BgKHYx8jwtNsp0f5WmpnzHJgS5AyobgS0ta'
    'XDUh0+ovHRyxi//Ab36qgf6FL56Sy3/gG0fAcqZ35YE2jJWcqwj1jBxWnbY6z+0uSN1d+3nLbnXsVtNu78K/oIwIFj0dR3lcbHUs'
    'O4d+UEqhXxb7aJDZxG2xCFYfqp12z9wu/dg7c3f7hREziVTevnn1sWJDMRjYpjLxxx9eVOz8FHEuGmh/pYEXFsaswDpj4JIKwpqa'
    'jdxf6QfirgOM/GdKpLWI6Ioj5OMPmf+REk3qa4nBOUG1W5y7JiGhCdLPTRKtSVfs9yWl35Ax0R4Dv7tzeV6ydfpjklCO2dYQvi82'
    'w+fV4aeKTa2honw38pLR1ATJYelMvGC2inzX78sOeHogvQPmQRmHC9MQ77CyZSoCw1C3sF0yIVG9F8CHTQyaayOeWTdIQMDkZTeC'
    'TPQknAJWEDQNmwXWrFIRQo/q9u0tfWF6Df8Z0KdAk1K1GMkuszcgATFQkdePfVdv3468qzwa0yBMLgziaMob10A8633M7q8l64+B'
    'i62rXNgexwl8pFX70PopJNZqZ6AGymZQfLne50L9a2hIlroGbQ7hcQqNwkfdvB642wdpSn37rAcqFbLI/h2vGc+Fl43XHRqz+inQ'
    'CKR9tVITtBNNzXR1MBsAvxGsCE70HAxisrxJyLLKXxjCaBbGvpnJkfjefwQ+aNVKMPnow6sCFVuWVaglB6EmzfgMZBKDsnVTHHUm'
    'P4f0WmlBfmx+fbi4mnh+fNTdgSNbgHHefaMYdqN2AJuAc6cJZSrLVb/+sbLZq4y9UbiXS+u/YxyiMIteuFBqGSLnNFYLjAay9Md9'
    'EM7QgxElM3TDJd8iZaj9FnsjMD732h38l5MfPzhLfNDIpJ9YbnEeTNbmNfJ2YUiBzl/555Hvx1jHNK9/19kF/Qz/wV+aVRK4tRkO'
    'v9pLkGqVURI/SJRPzAqgPeDBeAVSvXlpX8CqXx44pxdnNtSydMuU1pDgvoKzX/jr2M01SdKT0DmgVj9nN8QqTkyqRNOuA0ci6qXi'
    '0DVII2oZhSLVF22pMnfyF7bEdoYzl4aljxnX0DfRjG5j0IvYRufp1LIG+yKoHS4Bn0pJQ5pclGCJo6WqZLcAjShA5f7GcZyRzXFv'
    'gjvLAiUR6M1kY7HH4VTqQ/57e+s5Ij4Q/7WUNAaD2ecwNljQEicEFBYV4acptC1bmaCbNlWsaxUb9FveTNNlAH/mLWN/7FIcd1Qg'
    'sSCD9FNI92cI9KIYGk3VIJauSN13nZ0D8bva7pmtuviwqhzoRLbr0/kqypJ8U6ViLd1ldVk10e6x1EYlvM5dQcFUGb3psSq7I1Se'
    'PdMzk1DLStvh80nR2oGJuM5LSqvtEM4fHABhmKKVuurKqi57JdA4kKDYhzmrwj1R3eqZy/1WSTrNLS7pXlAKixaNhvFehnwgW7f0'
    'pCeD9ALv3pDvIl+sFccedN7BJgZqm2xuv1+ESWxlNZx8tpBBlJVWI0F/XW68P7PyjYACgyR25ir0M4tFyERDxVIrUYq5dXPDyOpf'
    'rSqV3dSpJeCWzh092xETdMfsihz0SLg5a1QDAn8uU7M0ck7GXCZJiDAjVvxSTb6FRs+UHYzcwYhJsDbSyC9j2yDmYqN1JMb/iCPZ'
    'sqytcfK/03ShLhz9J9gvSres791g7A7G4WiFZg1UC45mZOF4sX47NoOxZRuvD18eff5w+P7oxD2tAMEs6HwIRTL4i1dp4A8GdYI/'
    'qyX8g0FrKmeyA2EVil2TWC6ufa+yvYTS0xEeONuX/EcubQ+XG1vtdWz0OH8jYrbt2Gvvqte0l3hdBf7iNSv8g/al3mnThv87o68T'
    'Oq7vOe22jVT3B3ba67VthZk9aSBysqd9NjrA9k6hGTqkfEm+fz2ntWMLRz8fWm3augNjL4lAHaIUcseC0kgJk0jE73LaO3aMd1t6'
    'zm7Xphf2MIksa716BzKFi1zPgRmORI9QAp8T5PRWlwoNw2uak/h9gmHJnG35+cde3emogn/qOZ1dG689p854PTzCxEOxlyFFrYMi'
    'AHP6+WaFw7NJNFp4M70OzF3zVeDZat5nPXIjs1MnGQBz3lODKuEBGakl6LXiSpwAkBvC7x/4/2yGh8bz0KVeQO5YnOM7jy1bOKvj'
    'lN2mLT075Kf0mDkOFmiIVd+4qFQ8DGduhfCkYqOR7uoNx+cQ/YjAG+7EAyq0yXX9HKvygICcMMoPHtYZkxX2Sz+XIBxiIVFpuIrX'
    '8jcPNqZiYqj4oWREsvy535sVFjArAAMRwQITxU9MHSXXrvhEukQ3R2jOrLTHmHs+c4URUc+78ofns3bFvvFmy6nH6wX0IGIUBf74'
    'kNJ5qGhR8KNL/xXoZjCZF2QP4TreAp/RDLyYi97pR+R828uMbQrbz9O2bmDsnAGSKI7lpXimM+7rOWT5egcwhf32HGjArFAjFW7L'
    'IoXj6fnMuhGdVGScHtD1VgvvEhQyMl8YFD2KXD4woBLaWXOmrKkXja/wvjyGWpr54rIwu5aC7m3jNFEh1XRK2ZfWUUVtA7AQMC33'
    'y3eXzFCMTrNp+PET6PnSH7XV2xX9yxC0fTyVBm32fPb5WKS7UGrblKX4bOvui8QKYBjnyHWL7cMijQJKQE+PpTGZAdH2n6DHC7bI'
    'sXn7T1aLAG9h8VjQzozkAYLyzP+RYr31tQLbxhBD4cVpLbwlhJy5n2kGtgofmK1KpK4B6O+9a/sCFCdPY9C2IFfk0syjiUPbEwwo'
    'lHY0BGIkIrdl1Bpmnj8udD4jeUhmWh0+vMiNJuX42dlorN/mSxyrRQ4ImPwBJh2ftppn+UniRZUTOrWg3Ezb8i5GtjncPE5b7bMs'
    'DCH1OAqXnPMkN3Ztm1FbjLaZaBsJbyK0gfDmoTYOsWmoDSPfidgS9H1DbRpqv8jtFfo+oW0SJTtEFjDodJmmsJQUtV8ZJDR88q9t'
    'khrwB27w+BflBvy7WuK/KDl8wnMlQRQ0geO3bsdpbbd29tq7O52d7t7zvQ4IOGKdLkzxg5XPfff4bdXZub1FbH6aOkEkfS526ZpJ'
    'nYpYDZP/SsshfVXNllMz0U2AENzabzl+fefgEvQlpw7bnFmn9OqlZTW4BHn58HLiRSuTV10JnS2nwXKyuWwIekprENTpepWqRnIy'
    'Dn7gbls3lDp2lXXC1E42qTeOHVlWjHvwXFVOUq+LMjUTMU55D/+nWvWqAFEPaNmMqZRle9VRGOMvi3xciBBVnJ/isF23w3qK6F7M'
    '2bkW/QN7aLrUgVfFLpbOdcOzbOyDf6qBerOZG/8CCrlX9Rr4Dw0E61vprxq2wWnqF+txAsLc19JZN7BBsk7j6vrWIOVdoNsPqXtr'
    'ABDxJM7gVM306IY+sWNf6wvPZSDBFulqXKnOo9YSxsTQ+gDL5Cps6Cte4EpEwQI0UkgctJz8eDiDMPN5No93FdnR2KWWGlA4Xfym'
    'I2wIvFgwLkEY3kz6XXjjhtl2qqgpgWLXYhZuWXa95dgwGtgzXchGK4EJtTh4qXS94VZ3rBtRCIG/qcGymrtUE2vkSpeUfV4+9lxF'
    'fdjZMZPhd0CUQF5orfsWXpBDdexc2+nvtS2Jg9e7uJYPL5dcK22dilRLIPH6Gpm1nz1LBszBJBjcRPI0mLPEdJ2PWYmbcrlLi/VO'
    '5JvA3ARf2wcMycNBq1WfhedaackE+3eM7DiifG2FehrVJ0wxiWX186vwyGXQAH/35AlLQigy/EwUHae7Qlp720yqZt3ZqSU0E5gQ'
    '9A+oAd+Y0YacFiXa8MnF2k69JcpxIUjm7/4ddwoyoT87JgnbTDc8SLUDyRt5cC6VfI0kb2I2I+ySi8E0bU2toQJNWEXLzsx/2xw5'
    '0fmwKtyE1CC4Y9g5c0OgEawuydEMf47CMBq7q8sq9Vns0IL59XncaEd1eWwASjI6QV1LoOvEJcFEJPZ5EKs5y7hN4fkphDjJ+baN'
    'q2s3u0bAce2rdT5xzfwb+kSZgg+3tulkS6bxSdU2HVJBtzVXX4WExIvYr/Hor0EnXKNxunp1fXp9Vr1an67RG+sOkf+m0FG7pKP2'
    '4zqy19CJee26zQNAL5hcDydYNdcqZd0TswNqgeYcT7ow4W+7yXxKX27KGBDrOEiLAgo09Co9QSk2JWoUQRf2TNqyx7gMTBSjyEXi'
    'QfEcqkR4Rs8f/bFLLQGPq46iOrC3ahzZ+BVHNfwa4devkqRHa1fsd9DM2hV7IlD2ktJJCYCcJeXwl9aDTQ0uoZdfq/GSvuJlDb9G'
    'y+xI1pQar7GMTQXWdRrUWiAa6hMSyzqMufPgmuYNO8HzHdtpNW18IdXmpM6u7Wx3bKfTtmwm6DEui5gVntLFiYshG50+6x18wDAU'
    'b51hj856v+4025L1Ji6yjwYkc42lO65KkROfGXHxAp7p7O3aTDcga1Sdzo4F8ks+41fO6ItO04m0urbThlG3nst5tJ/DHDqYatlk'
    'KHVs7MwiqVbOI6G9TiJ0AAgd7Lc6/UDYkwVOTAKXfpgBSHzuJKi2nQ7IhbtiDr+6gL+whZuToIaic6sjQDPidSI5DYr8Wv2VhSAQ'
    '6TJpiAKQBr92nFTiAcHXdfZqMDUqQN3yg1tcZOiOw8QEXm/Z4yAeucPqsI4pI0ipcf0q/6FKuDBQbAA7mFqXYZ3Ggem810Au7Jz7'
    'AjzWTQonmtBCk6JhDesji9PpaqqWR9OuO7tAf7bTtUQpUJT0JdsGRNuF/9rbcsm6iHrPeckY9cTEW85zJfqOg8nEpUMix8bpgj5G'
    'B+AyH+OKuMvwytTKiNu9Zp2K2guQe4Bb2zsACwnvYE6VYEkybVO5jqMwDucA+18L1qVbxaFYNR77HhDS3h7MtgPrCUMA3aEGjVad'
    'Vpv2f+NOZ13iDKUl2B2Bx3NRIhmLTWR1yRvHiKnYc34duJ5z/eyZ+LW2blaXLhA8LNkBsVigeqCxX5ER4F9ifGlqXSb3oRrlAIRX'
    'l5CL0qewTyDY65C4ziQCuciO0r1Uaa2wg/bSZKm6QiqSlpRJYeT6oK/VoJHDNQTDw79i1Cq5LtP/1mFfZ4etdOzssJWmrQ2bh7rO'
    'wXdti7Gt06Hm0v/Woa6zQ2WtPztOYQPgcQqEGsktrU3XOo7J954+f1ECHlIdm7Wc619t8Wt9ZZu/gFTHLPGOm6CNFK/GK+1VCNVP'
    '3c6zZ0pwp213V3ISVNVdTV+HPWpZdQXXxXShSStt30qHj48eCY1fPMDwT0I+9ZSKT9CUnJOYJbErqVKn1gS6v4RUhMIT/1hLsWzp'
    'puAZK0kiM+p0fBIcwgpFfs2CU5A+v+AjSblzsP/oHvmPIsAuBq6yq4F4xd5eqOsMUrvaRa11BsP86sIPRLqvBLCvqUGu3hbCo+em'
    'tb6e2UP9E73neWBTd+hc14HSbOnqbkb4iR79LAoVHfvZ3gmaX8zSKeJkp95xyKffsdGbn34nNv3o1CjLZvf99JiR6QMYJjVlU1NA'
    '7fa0CtzKHtKvIfAeyy4UuoIs3Z6I8ysmovu2MrG0yX7Jx1ISz5V2KXXLX1i3JNVOuar/wsxUM3/uKymFI9WhCSC7qB1eVLnVA0xB'
    'tujWWCC4ANppw97U0Cyt3FBN+PBfnFXJMgbgw71eof0v9V8aUZXLVtmXgKQdWCnYMuzIIjVMy3C6XVjD5o4dsW1AKsOkOP4CIP4F'
    'cT6ahlLbbyhyAqoR4jOBa05uPa6O2lDN6nt1l7NAUNMXNkt4Va3Zqih/LVZmW90R+eitzVSrUjrWLy59N6QNvko6pKDPpkagvwiZ'
    'Ydx0U3vaUipPYo3HTWvf0TXibTIbZN6TOmg6vRbJTQJBAECCb2CWJPimJU0jaBzRmUKzRkBAPNqzrNR0mIF7X6ElAFZg2VNpxE+t'
    'W2N/lniu0GlFS/wwpTA95STRNkui0FgwcKVhXXATKQ2BdMbB4Ea++Qsd0p4GZ86vV3JCHVtZ2QPkN7Jbl9ASq1bpHxRyoCO98HqA'
    '9hMadM0106br8uf1GhTHatfp8yRqLn3c8fb5UL20EgtIDL26S/Vo8MCBroRvscp3U9rnhFSEQhafbl8pLolycuboXupqhAVkpp0q'
    'QJ9EDKLsagY8ATFfctRpCAhbSytYDa0yU1n1+K3AU3F68+yZwoVnz8ReasEGCT2nhxggKe5Uqb8qjrAvpMKxjv9iPxhJJjdG/D8Q'
    'doUeK7QEEHLEeX1PwB5PRS9i3xPtsGWA9sHSIaem6wiDu7l6LXJzqQJ48L++NGqANs2jSieRrtCSWBw1ZQm7NFcaPlSplqk0ckBn'
    'j5yoP3KG7mjoDBkjHlyBdDpp+CJ3pGazzevw2HmkbdC4HjuTXDWcCwpr8NfGOYkDLIvmxhlDG+eoMtQklmHs3o+fkvTpvoHT3K3J'
    'YzLYxJppQ140aukaFPH/Oh2soUmwCxhOvAOL4Jlt3dluWw2+kAEqqpVpqe2CGlfeGB017e1gm61im8/peiw5fDvdHSvXchqvyaXD'
    'v6qJo65hh7Al70mRyJuFLh4Lotkg3wFo6nhpHduVFGfo4qwqjTAF+bUD5ZutLg+ETY1IwfJoscpy7u4O58lVPB8K5XavbaMlA8Uw'
    'sUGrKdRwnMg8CBo4DqDe9BgxvfC/WjAv40AXInaVLdzqsADfTiOXb4xGhVfn5d4jSrtIoum2LpaVN3e5xuTpx8UbMMWas72jU7Yw'
    'ivgeRtAFPGp2NURq7u6oMxYMwP0ivBbKEEg1TnsH5BqnU9POW6VVgw2r4fUrsZmRNixGUacWCgezllUXXaTDgnQ3KzjVxUht+Rcx'
    'UesIBGb9a62jGXSOjixkJREIjCyLYZEpCBr9wp8BNLZrsMxVYUvg+vaOo6NuMH9HWz7IkTs15/km8mDDg0W50Ju9p+DUMcSx80t0'
    'bwAC26Elwrq7IJt2Wt2dTtVMj6ZrOGCAP5sqEM86aBnb3X2est2ORlLcbGqp2euSbYNQV+tYPwivOs/TVTyfhnFSto61DetYRWqX'
    'awk01E6hRW1tWNFqy+na+m8EYqZzWNvsd2Z1KYs8oXLEDoBpgOjU2tERuyOY0GZuBiu2q6+0mDWvtphsFf8DYoAl6+5UBdpYtayL'
    'QVXiiCygFglVdwzqll0gXJ97l0fuk8CXAJSImfTBSkZu4avSlp4OnnmTdW8r2shEC0WHiCqvDuBit6aAD7yZ9BNgndiD2LsbabDp'
    'NJAgbenSF+QxcgqUpZ2MB0SGfSCFltOWGpHyLCH5V06v6kKykCJ0JVccMWX0i5HjsYIhzxXYo8xkASB7xFY8oNLcoYQMi4b0l3QU'
    'dT77/DryzukDROaa5q9UfqaEHib7bgsPY1wxCl0fUy3TQkrTHFbCgBg3WMu8rxpTb93pPN+x68BOYLms2mMqQFEbaz2uPBWvf0P5'
    'Dh1i0HBQHd9JLXjZ06tOyelVJz29ergn1vmv8eSRf9LRWQO5dGPP4YvoSJiF06nMuVTxQOqL5j+IDpcYy4GuEcfRSN5AiQEdHL77'
    'ejKlq4lYwupDakzfItZATJUwWbQkSsek3T2F9HM/4bRjD3UDvAUZ25D+8sf3x2/fHX0++XT46aeTbPwavRo+dPUuPIcWlREtviP/'
    'VZBxz6HJPt6MFL/TUR9zgklj85LEG03F0ERRW04d8v9w9PHT0R8/n7w5fHX00WbvQutRNV9/PPzh/dGHT7Ku9B3k2rNgcSEHIirr'
    'cBFZKWBkB5D97u2H398DG1FVAkc2Tr2C+JbvNL3SKX05P4H49sPxT4AAq9nYwKBO5HXfMyo135nDFuSd+xm/TF86X/JV3RTS7KrK'
    'gB4Gi7H4hq/Djx8P//T5xU+vXwNk5A1fLEU/8f5voRRe3XuNyC6v1Z/WWzb8P/0j/6Z/ziyEFYLp7cvPrz4e/iyvcaJ2wpA6TJIo'
    'GOJbinQNQYK4Ir0/KzQk9kX9A6081+DuoRTlX2o5x/xOMebZbez/9bsfDz/Z7MfbRC+BJzLkBncauzd3fUVykGouFKNWZU4XZwcH'
    'pv4pJvATu/AVZoDXIlSjE3NhX6KPqyM8/loTkzuC5LRYUCgWaMWeZK+/7PJFFxH0IF3wT+yrACsuXaqd5SqemglTDIXZl2UgASjr'
    '008fj5q1rwpFirmf269srg9tvsUX8Nqvctno7O98/OHFIa1/+gV/f/pw8vaHD0evPr/406ej4iVuMtJhzABL9qBILsh1on29f/vh'
    '8+u37z4BVjI9Hh1+/Kb6hz/8XfV//nh4/PmEWOW7w/fHnz/9+Pno1Q9H39zEp5ImAjO9SIJRcyqwIhUbbycK1D189+7z+x9f0TUT'
    'uiBS2aF/d+lfdNeDP+rNC/ideZlC5IlXI+Arc7voTNt/WGhcTAJg8C5dSEDJRMTIsJOpK0MatdmFDCTBprqp7Z62ms1G7ExHNv+4'
    'HJ0J0UTda8JhA/90Y3VfSUVJomud2dI4PZLn0p7p3iXo9fVdCpWz25SGU41QOFgF3fWeB2MXSKo2DTAADHrDqWBXc4wO2vLrewet'
    'Xp1SQQ+Yt0x8wN1qwD8UQ8ubDWIHzzVhs4duMZmkC+gbfqPl8iLtgIVGhgfO4e342lVL51BgmB/l/KzUYw2KSTdImKg2/8w6HWRu'
    'faUAvL3F+FI9M59i5SCbBW2KLJZcSTqUpDrsStaQRhclLKraWfQqaQHN4/e2oCNkWj+ZlpfOXodTxbXBapcvrwFzMS7ZGv9SeCkV'
    'eusCcNiOE0Zee9g7rV/b13Z9ba/PbI/eJOldN9Z3+jomF27iDpL9FPVvb3lgTwWGHiQ9lQfKUM1UKHYhEMxM6qoE6Jbp7yziXVQ3'
    'FrQaF5aMYAiyq712C8RCXMC6uZYDrRIU+mtXu9xHSVa6RLBVKFffTLgyKURnKau1vd1Mactzv6o6GO9vxD2JA6NLV60OfB26LV6t'
    '6XqJXioNXqLLBi2RZSfpnUZYITkD4YFtR+4hOl8zXGHcbTNdeWi7qvpN0KRxnc742lZrAXop5GnQWOt5l3ipUUZs8cYuWYCvQT1w'
    '4Qs0B/rzzViEZ9uStYodPs7GrglxMUNYTXFxMgYFTt3eJku/5McsS3IjbZYmKvIgrWLZeqtlRVP1EQqH19CnXmp7csnF2DkAioyc'
    'YbYZUUC4ZlOJmI5mArOCKFixSzgd7iDM7az+BAaBrqwVqEnhi8wKecji9wV9prhYsbnqBuzEwgR8rCucoLF5dqioyAs3dO5nVtbe'
    'FQxOvz3qaLdSxSDRPa/QB3nmPVyXHfgKtdFx8OHKWApvFWerBxjEZg67Ojnw4ac0dFRscSuPUsUJh4SXfv+S8jVbhSyjJYnlE96o'
    'skD+luKzZ0/lzT9qE20GFYmvPFPtKEi2oqdRIWlrkQXktxiEdiwvS2hJGIBPBprDM2tX3VPlqHOiT3mN9fZ2wz3WNILkAj0o3IKC'
    'sw2qOVn0SvJasDDUnXMNWBcdoR+6eQlymju4oeYovNbpJQdzczAmovg5T3968PPM/lrdtvrcD0YEFVlY7E7AQzmCVGzZpwz8VUK3'
    'qU9I8wxok0ajF2zJgrpjBRXlQWCnaemO3ixygxS8YsGVw0NFy+MUwhF5XK0IGR8Ol+NXjLYM/l3LXi6L6W2Al9aUAv+Swb8UsF86'
    '1/bSWcN/Cf5I1gLUy6XMZ6dIyJvRqzcg/DWxTNu6y8JAgZaOrQlUy7iUJapDcy60zMbYWHAkgvQcDm+Iq3NfFNXxBAv+4kkVfgqb'
    'M/wcCYKqyFMmkT0Mr9NfxP/V1x/Tn39CsT9jWKbL6MoqjB2oQwL4KBpsK2cWKrIEdlCAaeUJXR7manyGkYuAqm+HdDJtXtlTGzex'
    'n90r+vvGnW7cEvlGrwiX1hefMl4aGQXEA1zkBgItW32151If3ANvfin7gorA3a4Iy2LS3T6+Pfzww7ujE2hlNzdqvpdsplu0eHjy'
    'hO5u09QFl1IvgbpXsBuGVw6/KaDgJhw75eeBIx4Zt/gauMpwRIgXRKokWhs3YgwUqs3qG3cYHwrfszduuKY+IopTlBs8V4QJZO5p'
    'o66DN7VlNJoyAQQPWFxTbgW3t+UTg5nMvDXuFQfPm026BS/k1it35LB4NHBbB9BYT8linTYLYxGKH3i8UpVFLcueZuptrtNI6/Tg'
    'E6lQIRn+h2jxLcNv9dopr4qvXL6sfe7TXe0Atk8i5/o2IOq0mMliS317145BPtFidsRXjSuo0SBG+D3ui/4V1KKw/hK9q1SnVlle'
    'V/r5IhLl9TLyLrykDvmtyOMJXt6/4odR16boWaAcWi1zN9O/fH9zdWf89c/G9zfTO3wR4/sbCbgDZhRsV6r0KvjYfeXOEG19UQB7'
    '42qrw0xBi46QrhUPRX+hJX9LXkU4OPjCZu4eDCdNdZIQjXEz/4QiSZkWDOYa3x/A81vfMd5h6JdIPB+Ab08xRYknlKRYZdBjBXEf'
    'k9fGOCQbLD4WK14NGBsc+d/50qu8AplMnLH/9m//wwjxvj29HyDKUows8YqgqFXhaeZflymCvQCpkunRurwpnzetVRHe1TeNlr8L'
    'vYX0jJXZgtLvj79kQ7OPpj7GXwHukKGNEw6ueACs6NLnKIZPBfOwbiQXQdt0H2Nn+nGiiOk10R/zHetOZ6QZbERumlw79ATfR3ST'
    'QUrNoLSdRWgegxav4vZWCMX3kLXgr4LBSTS9crMdTd1sVzZ6O+oq9FWju4NyIAwYswi6Lv6Spu7EpftO7uDUvMbQ2FeNtm226mur'
    'Om20hUGMAm+4MvTGs2cFeZei1N8ok8Zocp5lxfjug7DQPULqRRMI1UjlJqzEohPOBLS68AIQCV8W+Qp964FCDirf+d3JBES9XuW7'
    '8c5kZ2+3260QAECkwgfdX3nx1DxFGFR3bP5zxhAa+kBcxzAgU9xdyQTkdUEs4Ii8MlQqjord9ii6nIi6vFByxF7TBlCgcWFJN4VQ'
    '1rP6iwO5Gp9C03GcS6uHCRhAWSb079JpmlZx8Gc8PhkiHVqHaj8O0WnLoQhXHIG+ODYekMVNTgLQxwmIElKVAhjw24tG2P7U3qni'
    'qKGR52kDpj6UKEy+YTD0W8ao1oWvWmq33TDcyY7nP++IZWU6x5+kLGJEQBwCtMyp1IWvzFPbaXNEvnUxLfm31cz8FW34GD3Gl7PF'
    '+iGzwFabit0BN4uh93oMWujki+oCTytMKPa11rozfvv3//cLRuUG2bu2x73gV+us3hV94eWb9Mq5JDwU6ivWPQqFIj1PRzV7yF9C'
    'uRCIpBGPUisq33nbw51RF4lGh20K81xVYaHVqe84WFhEnhzEiuLTuHjEXYZT/gyjdtE6DW2p5hDzUR/Af0gIeq6PW1TXu2ihWbus'
    'j5SivJQDcsKwpM0NaO/ZnRzaP6bW0N7dSCx5ZG61W91WWwCcsGqIUee+v9nbiFm4DR/OgvOFW4GNPcEofDL5hRfTe/RuZR6MYbep'
    'ZFExXfK//rnSE5sxIKdlM1jE+LQOKCJYSfMUmGjoJ8EIxYW7nO4RL7wlbHlJ+vROLn4myw62Uh16m7ZCEbjpRDV4e4sRne6sjLJA'
    '5KnKZAJiIoMYu1okTxEEkDUQynVYGdo0BNH8Gx6JyVXUyKGlTOSqPodd7qcSSibwuj+64DdH/OsgOeZ9ngQSDv2YJlqbhiOUJlPa'
    'mBbhlZvCG6UNATMRifOp60IR60am0oErpuhF5QNFTUumgKo/gfbuVLSs/mqJLwFIMOjTyuVgECmQpFFQHwcxGfjcp9me+hQ4K1eE'
    'uxIl9OahLY4pjGrf7W2uLSkmieo0vxQgdCEygx4KEOHStLJ4lOsnMyDZTQaO9/UjxyO6SQPp4dtLdLZ/+sQ4rRRfTK/YlSkehL4B'
    'gf/XkF4pQLOah81V7PaO3W427ZZd+V3lzN7YwiW2gF4J5Jn27fXlAR38fB34M3zZi54NN9KMVtPu7OxhS3/5j/uaEsEFX8Af9Cmt'
    '8O2gro3/IiO6p6puZq/IF+rJXbc+Fck7GEn+wTGQYb3yLgwvDGRpRsMQoQ/rHYp9x/8+2IywsnNDqyU0Q2ESv7EVtrZXXoLGEXkG'
    'f5W3gE1knhXG2hkLduXj5ieOKxiaBO/MQ3uQhJuFGFa+zdTgXSk6MxrmxJvNwsnEogbL2su8aUwGQs2E+IIi7bI3fwVqt22ns/OY'
    'VjK2x4/axyNHIc2Vmof6o+sK42El/zgyrBSeabdySFfoOjWNlryk/A1wJEPr28UCAMgfj6ypDLJH43Nfw44JbsH+o5vRzLnUUPq9'
    'oYGSF50zpuAT/qU5cXNTzW9tSxiTZXsxfTaRp/wNjf1Ra2masl3l6WXXm07X5v+w6ce0+SetzUvJiP+2Fgu2cVqLvx2EWdM6vS8+'
    'kp/f1lLGLC+aNKYrX2/n3gZKTPmI75yov3ZeOrInukcQMj400lzaK9hhleiJH6RHiUoHmrHvstpqNq0abIU9Uz2OiL2f+5F5aR1c'
    '9i6VHaptWTVsi53deDc/FZEOg7FND7liAA+0Pdvo/k/DOMONU9v0U3v8OLh0VcRe9o8TQXvNCuRVrD78y6E2P8BOAcI+Q61C6cHY'
    'Dca1ykuZ9sSgVGQUbz69f+d+2fw08/c3wfhua/D9DSXe6e8tU9YfUELGJ6LFM8vykVrx8i0/dBvhufVWWkm8Wf79Dfy5E8+Ww4d3'
    'fSffLUeDob+Ejr+QgVEc6zp4MRdWAkYvJVp/5n6PMYv7/swJF0v2mcR91k3lZ/ILh9wLf005PujBKEA7kMBRoGH7Ab2schhFwDUt'
    'SxO98c06rk0TopDGrJCcBuMztwZZpCSQKP8HNmJkBPqMKRKwGuSq9/iA1EK+NxpIfwLNTPaUfdcL1rN2XzuxdEUI5H7OXOZuspZJ'
    'p9yTK5RM6MLVuTdaGz94qzgOPPF0mpGEdOsKjyr5hNb4CYRqqTnF/DQQCHkU4LxCgcBSsZhOd5lgteMkuu7yvTz8FfRs9TEZVCYg'
    'RCDzaTAbwyqb0u2/HCZSj8GQwhvoYQktYwGdHNSbzBXO0q3TwNMIDNiXIQPkjh3jI/xKBKMYUdsIGnlrDcEjLqDiq1/SOgXyJllu'
    'nQrPTmAsdiody9GlPrdkpfZLYSi7eoDwoYQ+02WwwM2TknUKL3/heoCPv4SL8wG9ssrGp/2GSLvvfXr5ihtUAaL1osCrE+G7Wx8p'
    'j+Pkc4Nbg7/+Of+A/UaGw+cLqukBmhFAdBbHDmzxyT77nqnwAD8qVtjK8ihiTHjrV7AlZ29vWzIlvJoDTS9LHvpGksOYp3MOUCyG'
    'GSyYWORZTIAex5K+xkBPkMpkw+VhoLBq+DLzZvhECjKvig3ocIkeD5Hob4bFxmGSPwaP86MkDX10Kv8Rw0vbKhkfPskrxke/eHgt'
    '3Dl0AozQiJF5TCEY628pIDpUal9tYlH0g3qFX2doo4AdJre90EagbxT9TBTyr3d9WevR2869zd1RUC91pCjGa2U3JsX5c2915tiN'
    '/dWuFVuSxi7YyDCtfDOjIUSP63xDt9G3dyjXItdj5lzArWUKprvyQ5NRvEx0MJoFo4uy9c3xbPGk5lcMeJVZrHqrn90Hc73elcw5'
    'c2CZy7wpuoGdnlnansEbBp4dauDNujzMwvypWtkLrYUi3/JWaxGjkED5kdayTCBZfrq1vwEX02e88wVqFYJN7phZPTxOgrp2Jowy'
    'e7+AeenT4GnWxoa55KaGc2jnpi8q67nljadlVcOoZfzlPyp3BFPxQKpu/cwt00H6fC0wiUyVzdhcIopmsViRs3w1N9erlUdyFNq0'
    'BgZuk58I0BZOz0cEHq0ycik+PSVFKyjx27/9z5hujhb2/0kQxYmNhRdGkMQleykJphmy0xSxUg2MlK/T0wrXJ8VyAqu1UL1WyAiJ'
    '15KbrTP7tJJcZ+2umrrOl8vTkmvdvrqh3Nk/Qtv7Bs0OBMXP92h3KvsRG3TaVMkG/Xgtj70rpXawSdnDUp8rtYd0vn+sxicP8tOT'
    '1VPtKOeMfUckx12WqIbHeBs6rxdmWf6xuDD9UF8MAhTyLWcajMf+wn267H+vOadu8L7RnFXvgKRa9FRB/CU7eLkQn4JklmdVX6B/'
    '9FFKRwPS/fc36Ukhuul4i9E0jCq9SgWvAJcIXIrAiICANkjCSpdV8FCCYj+ToRig7PHZs2CM11VEk3rpcmarmXOofWXSuZPzfkcN'
    'o7sbooTWV3HB1P6sz/IU7TvwP6PcooNCYfnQpEVKGRfYMgUgLAoLUq324pfy7axTcXXub70tB0xjNFuNlaervMsFUJGnONJ+lKKd'
    'NoC+VrDCu3vaUPHSV6vb7HV29rAWHvkUmk7ryutIAjPVIc8DVejaEDkZju4pqS4YCTAzmRZWumSNS1dW4q5aQ/H+urZL0izoYkmm'
    'MI0Gh6tfddCwsHgPgiQL7RpEvqyWpzvp8UFLtm8tp68K4ttOpeUw4/a2TUJZ7HnvcDfI+zbmigOYWweVlohaXumV5HcOKnsiPwbm'
    'sa1+E4rkrm5ok336tPx2h1hQRTO5c+fcGvvJpzCcmfjKJ78eRUIh/vrIVwVKnjESrqJ2knq8WbLWMfnhPFSJvXV4dbDWm6DAvLXG'
    'DyqvgLgMj00rbHuarR2DUlEKCmnbBQnAm4eLMdoZ2KGJnyVE24MNZYwpGu/w5C5cNA5niXE1xeeUpB+sA8B/iTIj1kdHUQ93CdEL'
    'JC1Xs5ljnNAWwHlc8Cs+hQitI7Mkt1DYVWBaMMMkWrGt3rLyCZqkkpmotEqdTL0lDx8PBBxlmeLRhAt8o5yyk2nks80pdoy3CZpe'
    'pPA28YCpGRxoZ7bGIKdsfwHxlzYCBCYBB2ZFhlGcD64fubviTfmZmB4KYDHCRw7vGGABMOAykX+OMnw6RoYiNBSM0zlkoCok2DEv'
    'oGMcUgZvNxKyS1hDBvXC96Lh2gCK9tI32rHxoRdhSXT2IDxI5w4TkNImrUkqf2QUTgpfia+ZSKOj/gjZCwGkl+T+TY5wKkTGzXXP'
    '9IVj+B/rkYPH5VYjEk9atzEOf69VV0X+BEWScIkl+ES+2r67Uw/pAr275qXNb7Eqz1QvfZFyaF9SLB01bhG0UwS19OysX38qS62u'
    'M1c4V2v9Dmc/0C/0pTdOZfzdhhqKule5urbSS5artXb7anntrtDJf3gKgv9y7a7W9NE5w7hFrnZTdHkN2ZY9vnaX1xig1x6v3eWa'
    'fuXulI7xAgBfKx2v+WfrTN6ZpaBuhziFe28p7m/z1VZ53xyhibcVCzdShYSUv4w6zd5GxTc4qLkL4JMUYV35YUqf3+xVdyxM7zCV'
    '3wLuQ0MbrhrjHUq+bHyZvVQMGfgYCeZbdwyGanKhItFiCkIzg+eadymgmYpCQ7ULuKQjecRx8HQkWmcSGZXyJyEfp6H5S/YxUl7T'
    'X5xr+xdnbTWyvWqwlzFYdZ8jcuWXQb/ozWJJr/ia4iNJVhsFBjCvD/HBCmyAiRaduj1nDclrkcyUCqt090R2kVW6fHIrTT2h/i7/'
    'dZ6QiKiLLKnMsVy+w3zPuRnaE/gAhzlvesIz9IGv+/KGkzI2pAc3+jkNEdkQHwsAXiYj0rpvFyT2re0LmBQPqqLuR53LSzHZhbTz'
    'vu4Uj3DjMVDmDIi2et2JXDpG87tw5DqOHtUlJaLH+E3b48jNItcv4kFUyEqKWSHHrqXXF6J9CRbrRgFoHPUJaF/7GoTusHiy39p+'
    '9gz+qPi+ta5eMclWZNPZHXk6E4pB5n7z9lZWGLS6CnM2Gs+xklieiAIf5qycmE/hFNRDoDdoxuj5jjdLfu+vD8Qwejgmm9hrD+vY'
    'HMsopXR+NLqnu66DAJjQO/Q9Xiu5Gr2M7fpOf52G4xLoPtzQ5Vvs1Vy6g/xiAHciv+01/lnfAbPclsD6ut/Ujpc17X/gtjQyOQQh'
    'RtgCULjAU6tV7Kd0cJfZIJVu9exZOvEB7B+l65CZh3Dn1FLILxJmgPxw3UNSSfgj4S/W6/kdW5KK5NukHI050xU95J16137VzC50'
    'qya1pnw9Eyq9lVtwFMgrYoG/imgZkucBKxERmV7ybSgT3TUp4e1Yt+zAjtMvcko8Y0g5ZXrx/H62p4RyMqsJ/gfs7+GjFlWTZpN+'
    'EobW0pWrqxx+kb54MqE9eFEYDtOFDJtRxvU4OHiZUOGlXSsiEWIVB6Asybb6KlEd+3AUxEJ6jXquArNrCGZn41GhDf9praimXS9/'
    'vnOaBeFZ2mOhr81AKzMc5trtI/mKWSDqS6OwhRlrlbHWMlLMvsvJ9Lp07C/GqCaZ1k3mgeOMt3kBT1dLV9TrF/JGyHJmJfmzME5U'
    'GSIOVehJTo3WDySk1r1BeS4tKlTm1GtclsJPzVNcJuMnDUJs7/kzEf1xaF1y6WeqZGwbaaGDyhvU7WS5XuUE8tRn1tpL5jGShSpW'
    'iQBVuKfML1TT9cNM1UfzoY19whKXZ4j1zWWWLK4wiWuPaN/bb5kVHrmHAZzDJwEQ4PqKfZXoqoI2d63du36xXZjLIwYjzG2w8Pwc'
    'xqazXVJacua5onqYDdrEedLy6WaDWWXyrJLrHvqxlLSPZyyAdjbUSdESdmZJP4P7J0dnElxUmM4KYMrY/R4Elma9q5mlVsPb27Z1'
    'n5Ww0OWSYxLm0+W2/pb5MDZBh++JWfnL/6pYGA2qfCrS1vnIufCdV2a42kFBrdx2envb6WJUFbwg0Wk/3+0+tL6nw2TxdmxfqYNG'
    'P25fVKD+dhcPCeFzGz6xUfG5C5/o4i8+u/DZbe21xWcLs1tafrtJrWECnSV+b1KHD7s06LO/Kp0EnSqjZ1yCkkflcV4SeQfFTY6M'
    'Dzst8saJ94oevD/FzAdvXJfsImUj/baWQajwEx/K5FvWDr8hFwTvUq0klXyF84hWR3cjuX8Q+ilVDrW/5ZgyMzR5yuWWn4JtOsNU'
    'p9TeeHyEbByN3f7Cj8yK4PoVW7B9EwO+Jh7oU7e3wBSTaAY/rWfP+FAWL/1f4Z4WQ8PIZX8t3xx8vmyGWhlfwerxja87fWM5imGn'
    'Ag5+UwLPwiRQtxTGieIkAOfproAsb/U3Fh3OVlHFLtmNNkpfGVsmwmoWemNzOAuH9sKbK2ust9EXwKtY9iqauT99fCey+DY1fFMz'
    'Vt9zppE/caEQ/JRduNg6fBP6krKcfArmfrhKTBw+tgZgDy+01qABy+4gb9ENUrE38dEBIb26aYo7TAcO9nF7W5kE8dRf+/U4WY3X'
    'gE/C29dsnP7rv1wZTv2scW5XPlcs4jB4XfJoHCQ54lKgQVvNC5iXeVq4IgpQnXs91R1ad+IKxlhGdtNr20J06cnx3eD45BcN1mYI'
    'jlWi+LbxEkKsUunrrodraT/2Yirex+U3JK07m2q2rTNb6JzeElkBlWx8jcNF5c6yU8DWKo6Yk0OZGZyBfSjAUy2EWWzCL088y44/'
    'HYYJ6utZqNzePj1t2W3txJeKC1hZkM3VKUyqHhO68gl9W+H/KYaIEa+WuG/4Y+M1t2/wxPkgYhLMyIagAs24grEDU7cv3bSLfpzZ'
    'GS7z4SIO2j2gXG2niAsl1N4hASKeUdOclXqb9hdkibrtXIDkUoT3y8z/7YI64IMczMc41pfqqFzErOSEftEpQHgbFW95YEBWlM9g'
    'rYCbYY4/plTEELxLKTIrC7p2giuoLqC8xmZ8rr9huOwsE5MEyNINlZbjscRL3hQqClrkwGSXIizas2filzDf4FFtmoZvtKzNa3cg'
    'RnrtpqN89iw/yGvLsmIhG8gW5t4S6/O4UPvFR29bXUtYQPKDwj2NxqRZlPbJnIX2H97NRSa2vARunC7DBQvY6Hay1vxPbOk/cmal'
    'MF+eXjwAciyxAeJ4YlrRDxDE09+o3rdgo7fXKmUtUpK0UKIZAdASptI1G4A0jck8Ef6NPdQsaS17+lTu63dasIjLjB9BBuniTJb7'
    '9Gm2bF/U13SSXHUth2pnvRCocl6FybWQz6ZmSk73qa1UT8i1omknBYGeFzJT20JdxW7ZHSvbMgnFpU1vUBZybfNrVSWqgnqAIyZP'
    'BNj8cIcr2fxQ+YDUt+iLxkG4aM9+kktXcqCHQo7BlkbGeuTEri8M0hjfgUIkEuPDDykO4vsGKjoIsmc9EIJ35UmejuqXaVn2Av66'
    'JTsQ7Yfupq1QVuA9R4uMUBSUXexhY6QFEgiw/sNSszxpWYmdTsgCz57pXyQDwEpnBJiDCk3MwM7wStAnDKIFApUf0fF6pVZooVbp'
    'c+CsZIrPb66GGDVrhlea0ZsAz6Lm+EYCvWZFLq3oT5DphPZM+ZJCFCk7PfzOvphwp9aUfXQqFTYAAmbgCF5Tt0Vs4uEU8InxRns+'
    'wBu/RlQxCWGs9IRP4gv+FjYadd7mkTcFzVoA5bd/+38qfFg8DBLgyKhrYeh8EZufVK8M5s1hTSd+DPs8dYz4iq8gTNzBhABMB/RC'
    'FhMSEYYbl7XElgAL2cqy5pfTMMS4aAtfC2dGC4POsx6wdBi53jBd6/JmMyMOrinkmnH84YeYl0eOFd/sFh3T+Xwp1cwnkmb6m0Uz'
    'hFlddA+bjS6RFefy0yKVvQjYoiLiGKCXGCMSeH7PonZlGGHRjfjcb2W/B+3yvY1xGuEx0WM9ZAADatskuHZNmPqVP7wIko/+zEPH'
    'J4x/c3s756W0nJiU4KZdFykqlKrEBY6Y+h52csYG3NMBFU7L2+VG7MmZlbvrQ8OFgabPEaibhIhSNG0S7A+cU/xL3FEIAoIvVFjb'
    'gLWhgSpBsdKoWIW0f/mXygbJQAAO5ok1KnKmxKNhcnh6bzL0agSilE1nmnsfxDEibEWUEsTFB2qMdqy+0CMXLyiXQGjf8ItASbCc'
    'rSksUq+yCDHyAb3yc7LkG9dScaoIaRmUEjpskEGGXdEhYD37DVCgTTGIOATNZegOhpyFQWVub4fCkQC/EGD7OfQ61CgNhGv0JgM8'
    'i39Z4ZEkkuIUlMOUeY5VrMEsRXrX4j2T9Lkb+H5/+MfP8rWKk7f/fIRPA/6qGWtZDu5zTR6QVfIAA8eIT6OYlb5WojG3f9iDJdhl'
    'ykMV8L+ecRDOMZsWYAkWA5zIjUjdhAhc375h6wbJKD38ZXMC+9fqKf+0AuQFSbQyhRy8lyIGwv0gXhiPe1Nl42sq3CDu2tjiAexL'
    'YSyDqP3//ZjKt43hP/NBFeF0kcFTICj4/gBFPn788WNeYc8/v4T7uggRSpTmGEckqBp0uxd3Q8neY6I6jM3rnXusz2DMOXzMQ6K3'
    'dFdJ3AGGGybbqMRhfJtKFnQ1mujnNn+WgtK2iG+I1bdkrsT4fipE4GDEtkf8u48R5YXFTexgrr6d9dPIqu5Cjoy+EMGFxJmaKDbK'
    'nWRbhnwR2glHkoa9KpdE+Z6hGCyadfKe/zhMYS97qclOfJ+Bq733Ey9/G2NXXywKkLrYFFV1UR5V1QeIY011Q1mKRhGGdwV150tf'
    'v3T6whuf5wdfHDGgGezqqbf9Yt/FsMV6TmYaZFVCLBVCTWzwLSEYn8I0lLxxGhTijq+CCRyFwbKnOAhrCV5OgdXEUnT3GhqOOcqr'
    'QzNhhlgeBVZMwTydTzDCXSoqsNCBr8wOcjt0Kjew1GBZZ7qyUREntEp9SN2ZUWIS3r9o9OQwu2SeQ59d1h0NDyVOzY5AwnaqG9BO'
    'pO82D5Gj3J/LSa1A1WbCTmh/5+Z1py745V98E9NimoV5iYjfN6RZFE5yhZoso1EXDfBoZ8ejVjpxKB4dsM58X/VwWbFT9bn0ZFrK'
    'aoIDaYe3iT8n6xKgDkwUMeMTmj4mKH1DHt/ZPVMupwtgrC5mCEH2Bz85jI8w9cAxpfju83cQvwrQFRPYTerxiU8FulRASCAfKQnq'
    '4qD6fb2nAMbLqI/S9HEUzgNYczO8sCdeMIM15uYc/HPE5VUmS6CiFSmfD6HkRT+dPcbGgMmLUhYPnbQOEFxZctck0w2DwCpYNu2a'
    'Youk7yYRuMgvkBQnvJ4mJjlhUOI7fNQn23UnetcTkl/xmIgTxUx4RHltFxRpRpesslxiZMnXx/XP2lrO8NAqp6jf6W+ThaOLn96a'
    '4QLpWZ30/LLyozXfsggjkI3NCsfPsOlSos0bTSW9BO7P+JQNm/FnhH8xdHjlAe6IS3OC82OuSKIblOpSHRIl+9Xd6MkbWkPvL6hQ'
    '6TOfMcqL3Ylonyi8snsJixuCvOmwVksunNfqVTK2hpeUM0NVwJsk4qHw0SqKKEwLwJ0MD7ozAPBSrXmP92bddVkaNh4bTDP3isDP'
    'xctUdiZY/M+Z4PDQ6RtUud8MyCJ4e/tz9c1gp7Pbfd7c070zhd0i1XcwlGASGp22DdVkSHi6Y4Ly2k6rbbw/hgKJNyvEiAdwqvg1'
    '4WSCnudirwHir2S4MhILPW4QBQmuJGsYaKlJNWP0hDqB3Qsx/xiACgwJCVMgtiJO9ocSDKhYx7yJV+fnPrDhMcpGPf3s6/PcwzuM'
    'zhKDjWGvce/0BjTsURSQr0ivAqvKt3eAdY9G/jLp3VTou4F1eqcVqnt2d4cP0KjJ8Fh4YIJ9/izy0Kku3WHpVFlaAA6HACmSrNnt'
    'h5ZHSdZk9RMXqJHwy944TWGbWs+yh8UlRCIYBLdQJBghZXHZYraiY9EYvmgrz6LFHRIq+voFpdn8JTZzWUwg/HS1uCADXhwsLlwJ'
    'zdvbG/zp95grglTBBZnvDi2bRIxeSnF3toeQ1FJEBXHC1Ly741dBUMDBwfJywVIDC/O9uVgx82f7DY1EEiSSveaA1Wxv2xtsAR+P'
    'Prw6+siPwbJBwLKHgA1v3N1t9TxL2Z1H3I0kuJTuT88BDOX7tFkAlhgI7pGndh+QpjJtP/Id066NcOHp3fueKSy16l6fEr8//P5I'
    'vJ0r509lJ2k5MSoeiF6BXmF+9+PHz4efPh2+fIPvGDfte+ZFT9tKPZeOBbTRnDDdZbsQOrCW8hnffX539OkoZwRW1IpBSkd4N1LI'
    '2ok6rlZGH35f+w2+kkfAU/wsxTEG6pv6mtHHzb0J+3N1Wt3OvhDAD3T/jC/wYZfEYXSKzY5X6OZcYMaHA/J9h/RhQVzen+tsv7rn'
    'sSAkl2scbH36Dc8EGcraxS+J5Od4xXOEmig9HlMZ2flmZOO2SEp7tDEDVUTsA++LGyggysMSDbwYLq2Jsc/2p/hvrWbhutAbWdyl'
    'E6+GHg3cnNZbdQwLVb2qbtvwJX9bNkaLqv5cu7bk6kmN7gsvCIc2+/lbnjAh9ZyWbDILYbDmGjuoTq0GYMkbi+IQ3P2Oi4nFqYq/'
    'd/IqdIOm8MXqF8XoiF2khRdPBCTEA7/josBEHeLRLwAahLX2VJlz0iLokhBPhVOEZO9W0f2G2bV0YEm325znir57KyVQgNAffysE'
    'caenCGupsQItD0pt/WJldGOYAvRrpZOjPQdvVpCIK6QR2D04A7Quf5OiqhTTh5kjM1GKzi64pNLE9VopD1VFJVMvaO5Fnr9RG8dT'
    '1MxG2tdU6Y2SA0khQsigomWOrHSyKB4nK+rOoMOez/AcDcaE/uLs9FeiQRcPDZGq5/4cdFsD9AZgx1NvhbIg2kGEk3VsiKYNbBsD'
    'M5IVE+VxKETRF32SvuRBrBBlUfcoOQx+st9gAXLwZF/+aFQNJB6SiH96S21iMA5kNbaB8TTQE0wG+POJHQQjdYeQJQWj2nhiSukX'
    'I0ZUUNbGY6MRRq8QL167mSfm+qwZhcvAHx8BaowSIYVxyxRNXQhhZP8H/YoLjPBVDBLFhMmRkxOYhNu0xVtfvPK2uGIpvoD9LGkJ'
    '7MibQFm8AgN/0HoiepLPxS5AqSxXSM1KenRfp4LIiNP75KAIzsLMW9tZY4Tm/SQPeE0RHvcM5EHlWVIaB9gig5x5ai8BgBtD6UIz'
    '5s19Je6IRUrDBt9Ew/I98ewrVetxwGNMwRdKp2GAvoDKX+zOFlWyPvui6g+YaOCRyQwPVOK0gVNeClyFM9VGxtFfNPEpTUPdgtQ8'
    'hMkDTRVuCcj2TqZ4BVbwTN5XKLu0NYSPGT8Udq4Egl/SG60YtlFEZfsiBvFFizWKG15ZhK8vuF49ijCHD+ph5ElaOUxqyWnmu2Ej'
    'y6Zu/o6G5T2vjU3LCJfmX/7D4h7orhn2gH+pgxbAU4IU/dNy0BTv82g+gxdZzJXXBshrLY07nkYRU5HGZADxbJYKu6TCQ8iAZmdn'
    'VtkikhMdzf/7m4s7NXeOASWnLkOHfckQGEATp3t/q+yYtqFdmbkBMe80DyrRS+amP2+AqV/yoTNeRbRGJnHOjBczyhlm9po+hnvY'
    'FpcR/WBmyvYy9/GFuSmtSk3TdV1zBFowxt1OXz3K3OSHPQ67zPBpofvnX5nzJlafODUFA5SZx1AzfxKDafLBwooedVoarm5Ev/3M'
    'jpDZ5hsN4wh9OmU7BkdLS7c+aWNTex+/+xD3jQVsFLDXMRQoyAmUDyKDbaYy7K2sL+s5ujs5PwmaLppIYT9rapd2OCsXLPMlYouZ'
    'WrzHrlyvDMxwhy/GRsMGtbjtGBnte2Bq40xa/CXT0skoWg1FlCsoWprHtl5svbBwU3xgWL57iTFTXBPLNQQmqqBkfX2evn+B8Ynk'
    'EtJOr3C1mUZJkVO38chHLjRjprj93exrQCt/fChBrzB6CojvK8vHQ1WQOBXuQQkILE1aNyRPQFVC2vKXE7F13RiGc6m52F8da1sN'
    'AECzrxoqWVYOCgHVBgh/kvZRrrEw6Xe0JHSbnoCEXxJqeJ5QPnmUxNUsHxi5zmmW/NRjzoasNaZWTOtLTh1Bqy+NdikfQwEt0ud2'
    'DZ+kQ458qceoUHBQLIplQLX0JG1LRsOyPgJ26UfkLQYsxwEg50illL3gPBR/eXB5telq4BJ3/BSxMnd09b5ZDq5YdgiyL+fLQIr8'
    'UYwYr51E4S4p5U9L9hJuvELD4wF4hoJgQWlBuTzMzB2oFDcpOQARmTKkW0d44iPSxeTO2AMqdAeyUdeFuViWPhlM0QED2+KSZetU'
    'XB65aovJrM7LcLnOvIY1yi4eqt3ZfE3ByBR9K3vVgvqNSP0f5V8U9V0FVt7i+JTVoysBI/ph3d7KMijU3d6y+L+xOJPxU5/iP943'
    'JvEKq+QX2ivkgG/s1I8bFLrzh5Uz7YFRvs7MtMO+cuixloQ/wQqKy2aUKjwRW2w2kZE7Yd2F/HGgfqnwSqP/r7Zr6W3jusJ7/4oR'
    '0Go41WgsJa0LkKEJx1YAI6kRWMqiNQyEIgc2Y0kkSEqWIA6QVdFFV20W/Sfd96f4l/R853Ef86BkNd1Iw5k7d+7z3PP8zhu8+Dbr'
    '6wVsaQA89e8c9Evc4Qc4KFoqk027f4iS42uUZGRUXxRPcEubtQYqZ2tNLBNd5TNiIulQm1VIJnxV/ZgVP83pUEjzJM369EBXcoWr'
    'RrKTNOkdJsOEqO9vMwfgKciYMoTHYAbc2TYRzIjgoBy4ki+U3QoKGwfWWv5ovBJcPytd8g1f4DXPfgT8NylkSZzMuV2DoKHfYDVk'
    'hUhOutkLpp1MNWqb20YzxWtJT7ZxwhONceC7zus7Db9zMn/AV07mzW+czBtfcBuCUSVasAHvswxoOqN1AN4aK4HOF8nkodxZjxrw'
    '6W//SNDXLAEHMF8YuB5nPxMxP+HpKRLJcbxYgAOUkVCOb04S2PtyWXSsLwHIYCPkOFE31Fm57Ce27gpbdwFpZJzoY2Wj3clxiiN8'
    'COob8XjL8eQDdARNA3ohDd3HgZtmb5UqnRFZ8qZrPAt59gF/ZWRQ1VECQGCvCEntZREAliPaLZG2qmAznsCIK6+DoZcfBO6nRYgY'
    'SBkNHxZwl0MOPjM9EBd449hBKRIyGfuH2dsRVSvZMZUGx1xILB84rdNAWQugmzQUVIuxxG4EkdBZbeZE9RpOFy3D1AOBP3KeUzKu'
    'iWhCpwJ3+Onv/3r8fL082/sL52G5mM5Z/R+JVdwEmgzHZgyCc3UQJ6NprJmufDSe/1QGPfL8mTDHwUJlcO6wf8+vfmBuNreqyPnh'
    'Ynw1np3hfA/QKdNq8MC0Mbo31hiK1PtTyybbXhOXaamL99ler7aCiQjYJba6vR7IQnqsPKYBhyTEglBY6KNEXrnzpKXgenzKOwga'
    'cHmzXD9br5ez08t12UNORaQgE48a34SojE9pk+Y4N9nTSs7O3ITi39w2j0CSFTktzCpPrIFcruX0c0XxPDrKRnReyw0GDOVvCGG0'
    'xkYEC0Ps50zy8HTN2YroOCJyUKhl0sDKpPo0Omt8/zGltdYmn/76SzibyiBzcTPm1l4yMn4+mzJlvKvBVq6lzfYo9YWET0q/AUCr'
    'Sk5j/61BArvEcgX/UXUemq0SrSPqgb2RVVE8CYAfNXsMT02eUuHUefe9W9Kk3NEflAn7QgvvfF88UuA4Qh+QIjbRDFLpb0sHf2Qc'
    'XFqddL9iDQvVoh3+Me4J3uJeyN02CEfxOSxkW+wMhwebTSjTtplzuC4j307QdUcR1mVIgIMRPMP4McG966TObKFGQMqOiOQlkCG5'
    'JWLzZEvG7Wzax+cZorHvHPDC0dxsUhzhaX7ddxi2Cumn2zq3Tdv3+1ciLvo0pDkToj4IaQfmppCqytOXbchNsMYOmvMTAMclDjpu'
    's8HfgsHv0csYRk4w1wJgXi58nT3m/4LNy5fcFYfkyG/RrAc6DP4Y7dsJsrJOowRFyshEBUROqxw0JD0yd00e6UzHtVVv9eTgYD8Y'
    '5sBxTmriNwXVTTRk0BKpmTsEqHOfxJbMfI3+o8Vh/asy241P2qvbvmoeqGw6H4YtDWsYbOu5vLtvzbpPp4Nu6dv6ARn9zjPVT/v9'
    'jtaW8uF+DlVpkb4pDr5tW9eXi2HtjsKPsUOYt0YaW1lnJaM6uxDGjjjjPfBmtkOOxRSr85Nh1Zw55DtkvA+q55uvOVl0O7RZpyDw'
    'GTtDi+61tWVEq6hfHMJ1+p594nEEDdNzQglpS+60yoSVJU3sMuKgX+MOmEr879DP+Ti64eGBRNKpCpAOxLtOS/yLUzKB6fuJdkOc'
    'jmmVahu06Xgvq2Jx+uh8sb7xuqWaajzQq7Nv1XmZO81qh948kkFICu6x2Rm9kkluuhjbrIMtCj8/xO52OmAIPeBaaCogGzeUwasW'
    'n93mCgMZh3CRsRj3DAEfF2pS8fLnnfKK6OssFOCmrhyE9o3qRmyMWXFyeYVxwudDFBBREzOiN/a+fHIw8PCi6lbMdXnkDRR28yFs'
    'KMyM/H5PW8cp2zcb+8VZ0uVnQatAc/04M26ajejDfV/Zvl7NLrLfFV/8QRwD2ht1OifZAUuSWrWjnTJlLXgO40nTvRfwCWHN+l5K'
    'P4W0E383P+9hzapj05dPLAr6i/yPMmbctXw9V16El6BjRNxI/B7QcPtsDctFV9ZP4b4yXiK6QBhue+sroghuVSGSam2+LsT2ns3O'
    'Z3BuIe6RajSRpLG0ZJ2yJXfSIC6RqUEpTZxgYHETqEqa2u2GxjlwiLElO8m2a7ktjqimQ5C6ioTLJ0yZiO3nJiWz8/NyOqOJOrsJ'
    'JQGZw9ySwXKGCBL3WPcVyHU5+wnJ4DdVEfS1WDsUaeFj1lrm61emBEJc2ati2GqZDtsDJhJo7YGdwOU0QFdYZhsqZIWcP/rDsTi6'
    'u63wXlS9lXr6JOwX1iK/MTUp7SN76JbXk5Luhesx+ROyys6XiCBYrkvJrKo+I7FtrGMk7lbJhO2N7BNM8aJGS1n9MOepYwx55NuY'
    'XRhElgtBxHDgseAk3INmB+fD3bSbCE9RFG6XBL3I8v+dIgkR8tMK4rKNFvD56Yt30IZIvdSqv4WRUrkAZiRGolgPb9WUs82tr0uL'
    'dk66VzPz76We0sU7l3f5c9aK9xhOgtgZNJt7YDxLJ+1y/NwDzU/51dBZn+i4SUevxq/6CipkD+STDQSwLLsNeXNHuP9v1jux3YUk'
    'LNQKA+hBUAwbyztWHgOMUICpDN+FbXkCqsFxZnOS48TI1mbzeNPGMzdNbKFwRWOVve2799hMF74LBuMqYgOsLaLv+RxBFvUIWv1n'
    'iKLy8WjvUCN0JWa2jUQA7WBKqyilrEcgNO+aW8P4OMwx3X382d01MsJUR8wGfUdaWMnNDqRV1UQhrAMQDlmAszw6hlBRR7bZbHZi'
    'jDeBVOJPKSBNdDDiXGxFVvFnonE3Eh3AagxUw126tSZEBo8YicRVFBFuUPVzgV0JYrK5W+6MATjABTKW14Cx7san5L3Wd+2siKlT'
    'X1nbk67ugPLj1nP2BA76xCbACZsAA4PE0Jzx7tjONaChD3RehG4o3tawBWVIV3HWAprnNwHIjZRDQo+IWXVP9iYx49AxTzThzKOt'
    'nI/swaef/xlxszVAoA9NpwEW7o247IT2fkX1mQDvr9/sEW5Ti+nfV0xI5PopU5H2par8ChNzxgVDpKBXltsGxeEt0AF0Ws9YNujL'
    'ZLGIQNcqKdCVExe2qS5VTjDjOtMzzouWjuzCCRF5pK3v17T39CqHC0s2a2sw0xG3TpV6+EXKlEPWOK5o90s2j9hzE5EmQknsLGXm'
    'B7dGhRxMvOkmbt2PZOHDoXbA3u1yE5ejkaijYuPoQWj/rLlLuWAJt+a/o3oCvwNUa4xMKOIILsitRMqA8AUPFSzk+GK8IPY18Bi9'
    'RVP7AXV2/vzs6Giu+1FiqRJ1uUyGgI+Yguo2LbJeicaN4pIjVoGPHCuJe3wr60vsChNMrTQeNvFqCmzS/K6z9Y7i3/1ec6yzmnZF'
    '3sA95B/3ahabi50dKaG/d3druho3C9Wj9qDt4e07xLuK85sfdb1R5fxUKg+e6phrkFzuZic3op5jPHOecYvUyGtTnMfTJIHodQcu'
    'C0b34nGrhGvFAply8IjdMe6C3baDQqwfDgQSodTsDShGkdlKtWo4rCSi90368tX3P5wQbURs0bPXR8/o8vjou6PnJ2GqWK1gPX73'
    'imHIePF4veQLNt+HCtKvwd0DYyzNdnd3pBl04aDB+VqxwflaMjBJmKRzq+gABl/PF98v54vxO3H0Bl0KfTQqL3Hh0GrHI8e1fBNX'
    'hjXe8IU7c2PJEVxnbWMIC6oMDHruxrH+QEd1s+nF92UCdndx92ZRSprjC4CX1FuDsW1BUUfLdNgnVM/24Qs1NJUxvfr2Fd4Oxcq2'
    'CiKFR2X4GXWHUreU6WfsNb2eN/IKRK7OdQrd4cIcf1VJd2f+B5VH+NDoJvm1Ss3B2xKEl4i9LD/09mKYj9oAiKdL2D9oitv8Xu31'
    'mBRctLzNak9VJ0Qfe12KvS1Ig+N3QlwUJ/WWNAk1hUSbHkIWIdNGDg4+Lte9UJCUeC3HcWbqw+R0Uhz+RccK11C8HyPpoxb87HPb'
    'JCNTBHyvUQxLSQUYhyCEfm0uHCE5Une2D2W50AgGdgCEru9krkpAMJRRco82R9TceQcYB+ZdBB7gmMo56cOFXNdU1AVrGqVK3kJu'
    'Anmnq4TPdd/Qf+gSYIT+mi9mW/aJmmpk0qYAqHOTnV6ereqjSmFdYsfRh7dFueEOX9QuwyZaoQ5l29xXFvArg0sK7Y42l055GDiC'
    'iMgyXt6knZ7arKru4cWsmxFgrRjy2fF4OIc4EOYtWTt4HbicHTtSuSLkIjBaKFyWuZiiyujPlkplYh5U633SbTQDLKoteTqIPyjf'
    'zxDhiZc7Y654ZM2SkW2JG+Y4dYOZQypWYJDd9H2YOsfHQ9V5itTMCTumldMXXw8SDgv9yGibCv7G/C5HqJDceDG/XCHB933iir89'
    '+vMwSrYxm+9rm/avDlMJHxae1OJALCfGS40d5rCQNM2np4oqILcFacGsK6q3BRDgXTZbLtSxsuVZq1eekG73fhSC8to6oDm3tYfA'
    'ehrE+UNki3AVYWQyJJ1Tpq7G7bveEgMW9DyEKKNhm59dQREMJMYgL6tEvwxnNqMFotB7tWlI4Z+rRYlIXS7eLUmkvyhLOMz0GHxN'
    'ntFniJWKErkcQ4RA3D5P1CoNK1pdTibUfa2CW9iLqwpLl9BAaFnU7IryA9owxLPVIMA5Hnksqw4B0Llc2wk2PVVcHj+mTil2n9Fb'
    'Xw+np0X4Ed/PXFJqxMOspdbXxbx9cIhTvMYxMIfYti7bRmbkhoaLyqjwJaNAhANEd/nxZuPe1d+qzdGNT63A/r70DrnUkiqU/j+O'
    'l9i3upH4GGlZ288u13PGggxqSj79/As7ywMyS0kE+BDmTRgzMsYyL9IoOw/1mziUSRn5ITgisNlIi2jhwxa5u8tld0SzEwgZAGJy'
    'PN5lOazn3vF6ZEdQHpIZR9i6ig9qs39wNKA2hHf8sYw2KMfLdXneI7KXK7vM5EtO7JbRPWbCOleL3JROdMRZeLgQmSNoEmq7wGBB'
    'Qxh8N4R1SYxZBaLaQzcSg4h8tjeMdZfniorCp8WKKZoLDiDOQSt8iBUv82BasmGjPQdEHYaGSXNWWJAwg38FsQEh5jqgtZ72JGsS'
    'p4Fg1pBVkvyzFY7dlcPhx+WIzuSzqfjP+eNnNh3wYtUzX5TKMnC7uzam/oqWKNXxGX2RMIKevZ/FSDF+6tuAYYe3aJot7WoLR+IZ'
    'C7yRDbYwRFez1ex0BkhtY40siVw9nJbHhZm2XghZGGHCuem1dOEfh9Fmeec3i40ulXHuV9gZYdYCPBuYEvB+SQii01gxmYx48xRM'
    'jxlf+WFWEVUs4rpqq9ur++7MOiJVBWlH1FdV7rsVKSDvSRuCamPBzS/ObmrrTdyg4hojHNV4JIU2GSUXAsDAxmpuSiMYLoGfNWsO'
    'i9bs2fD0NkglgBOYgVDfiGsTNuDbXK55R2qGc/eQdUw0usJ3FJLtBtq0crm+kcwBaXOPp7kIoVoRyIE3B8h+l6aj7+1Qq9uGwsOW'
    'n5ZutnU02M/Vk5DacKuOQFC9ozW4PaFMY0l9FtC3T4QitQSwzrm3oYnbUI3gG8CCO5wCvPXmqUFbdJQeO5FDv/aff6v8UDvm+p63'
    'wIK9QcHoGGxSw0ET31I/wxqUaL8XTaBLxOgqZpaXOSI0SxW+LxfYlmbLqCFOZe2y1+PT+fQG/9+vz8+ePvovvLoD1g=='
)
# END EMBEDDED EDITOR

if lux is not None and not os.environ.get("PS_FISHEYE_IMPORT_ONLY"):
    try:
        export_cube()
    except Exception as exc:
        traceback.print_exc()
        lux.getMessageBox("Cube export failed: %s\nAny completed faces remain in the new capture folder." % exc,
                          title=TITLE, type=lux.MESSAGE_BOX_CRITICAL)
