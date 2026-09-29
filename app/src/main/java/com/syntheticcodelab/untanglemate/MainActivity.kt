package com.syntheticcodelab.untanglemate

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.clickable
import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File

/** One node in the tree, as parsed from android_bridge's JSON. x/y come
 * from the exact same core.layout algorithm Windows uses (see the bridge
 * module's comment): root at (0, 0), branches fanning to both +x and -x,
 * not a top-down tree. fillColor/borderColor are null when the node uses
 * the theme default (same meaning as on Windows). */
data class MapNode(
    val id: String,
    val text: String,
    val x: Float,
    val y: Float,
    val fillColor: Color?,
    val borderColor: Color?,
    val children: List<MapNode>,
)

private fun parseHexColor(hex: String?): Color? {
    if (hex == null) return null
    return try {
        Color(android.graphics.Color.parseColor(hex))
    } catch (e: IllegalArgumentException) {
        null
    }
}

private fun parseNode(obj: JSONObject): MapNode {
    val childrenArray = obj.getJSONArray("children")
    val children = (0 until childrenArray.length()).map { i ->
        parseNode(childrenArray.getJSONObject(i))
    }
    return MapNode(
        id = obj.getString("id"),
        text = obj.getString("text"),
        x = obj.getDouble("x").toFloat(),
        y = obj.getDouble("y").toFloat(),
        fillColor = parseHexColor(if (obj.isNull("fillColor")) null else obj.getString("fillColor")),
        borderColor = parseHexColor(if (obj.isNull("borderColor")) null else obj.getString("borderColor")),
        children = children,
    )
}

/** All node ids in this subtree, including the node itself — used to
 * reject "move a node into its own descendant" in the Move To picker
 * before ever calling reparent_node (Kotlin already has the full tree,
 * cheaper to check here than round-trip to ask Python). */
private fun subtreeIds(node: MapNode, out: MutableSet<String>) {
    out.add(node.id)
    node.children.forEach { subtreeIds(it, out) }
}

private val PRESET_COLORS = listOf(
    "#EF5350", "#FFA726", "#FFEE58", "#66BB6A", "#42A5F5", "#AB47BC",
)

class MainActivity : ComponentActivity() {
    private lateinit var bridge: PyObject

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        bridge = Python.getInstance().getModule("synmind.android_bridge")

        setContent {
            val textMeasurer = rememberTextMeasurer()

            // Two-step handshake with android_bridge (see its own big
            // comment on why): get the raw structure, measure each
            // node's REAL box size ourselves, feed that back for
            // layout.py to actually use instead of its own low-for-
            // Latin-text estimate, then parse the properly laid-out
            // result. Skipping the measure step is what caused visible
            // box overlap on a wider real map during testing.
            fun applyStructureAndLayout(structureJson: String): MapNode {
                val structureRoot = parseNode(JSONObject(structureJson).getJSONObject("root"))
                val sizes = org.json.JSONObject()
                fun walk(n: MapNode) {
                    val measured = textMeasurer.measure(n.text, canvasTextStyle)
                    val w = measured.size.width + NODE_PADDING_H * 2
                    val h = measured.size.height + NODE_PADDING_V * 2
                    sizes.put(n.id, org.json.JSONArray(listOf(w.toDouble(), h.toDouble())))
                    n.children.forEach { walk(it) }
                }
                walk(structureRoot)
                val positioned = bridge.callAttr("apply_measured_layout", sizes.toString()).toString()
                return parseNode(JSONObject(positioned).getJSONObject("root"))
            }

            var title by remember { mutableStateOf("Untitled") }
            var root by remember {
                mutableStateOf(applyStructureAndLayout(bridge.callAttr("new_map_structure").toString()))
            }
            // Expand/collapse is UI-only for now — does not touch the
            // model's own `collapsed` field.
            val expanded = remember { mutableStateOf(setOf(root.id)) }

            // Where "Save" writes back to. At most one of these is set:
            // a real "Open .smmap…" sets currentUri (content:// — needs
            // ContentResolver, not a plain path); the debug "Load test
            // map" shortcut sets currentDebugPath instead, since it
            // already has a real filesystem path with nothing to resolve.
            // Neither set (a fresh, never-opened map) means Save must
            // fall back to Save As.
            var currentUri by remember { mutableStateOf<Uri?>(null) }
            var currentDebugPath by remember { mutableStateOf<String?>(null) }
            var actionTarget by remember { mutableStateOf<MapNode?>(null) }
            var moveTarget by remember { mutableStateOf<MapNode?>(null) }
            var canUndo by remember { mutableStateOf(false) }
            var canRedo by remember { mutableStateOf(false) }
            var isDirty by remember { mutableStateOf(false) }
            var menuExpanded by remember { mutableStateOf(false) }

            fun refreshEditorFlags() {
                canUndo = bridge.callAttr("can_undo").toBoolean()
                canRedo = bridge.callAttr("can_redo").toBoolean()
                isDirty = bridge.callAttr("is_dirty").toBoolean()
            }

            fun loadFromPath(path: String) {
                val structureJson = bridge.callAttr("open_map_structure", path).toString()
                // Title doesn't need measuring — read it straight off the
                // structure call rather than round-tripping it through
                // apply_measured_layout too.
                title = JSONObject(structureJson).getString("title")
                root = applyStructureAndLayout(structureJson)
                expanded.value = setOf(root.id)
                refreshEditorFlags()
            }

            val openDocument = rememberLauncherForActivityResult(
                ActivityResultContracts.OpenDocument()
            ) { uri: Uri? ->
                if (uri == null) return@rememberLauncherForActivityResult
                // core.document.load() needs a real filesystem path (it does
                // its own Path(path).read_bytes()), not a content:// URI —
                // copy the picked file into our cache dir first.
                val local = File(cacheDir, "opened.smmap")
                contentResolver.openInputStream(uri)?.use { input ->
                    local.outputStream().use { output -> input.copyTo(output) }
                }
                loadFromPath(local.absolutePath)
                currentUri = uri
                currentDebugPath = null
            }

            fun writeSaveTo(uri: Uri) {
                val local = File(cacheDir, "saving.smmap")
                bridge.callAttr("save_map", local.absolutePath)
                contentResolver.openOutputStream(uri, "wt")?.use { output ->
                    local.inputStream().use { input -> input.copyTo(output) }
                }
            }

            val createDocument = rememberLauncherForActivityResult(
                ActivityResultContracts.CreateDocument("application/octet-stream")
            ) { uri: Uri? ->
                if (uri == null) return@rememberLauncherForActivityResult
                writeSaveTo(uri)
                currentUri = uri
                currentDebugPath = null
                refreshEditorFlags()
            }

            fun saveCurrentMap() {
                val uri = currentUri
                val debugPath = currentDebugPath
                when {
                    uri != null -> {
                        writeSaveTo(uri)
                        refreshEditorFlags()
                    }
                    debugPath != null -> {
                        bridge.callAttr("save_map", debugPath)
                        refreshEditorFlags()
                    }
                    // Never opened/saved before — nowhere to write to yet.
                    else -> createDocument.launch("Untitled.smmap")
                }
            }

            // Every mutating call (rename/add/delete/move/undo/redo) goes
            // through this: apply the bridge call's own re-layout, then
            // refresh the undo/redo/dirty flags the same way every time,
            // so no call site can forget one of the two.
            fun applyMutation(structureJson: String) {
                root = applyStructureAndLayout(structureJson)
                refreshEditorFlags()
            }

            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    Column(modifier = Modifier.fillMaxSize()) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(title, style = MaterialTheme.typography.headlineSmall)
                                if (isDirty) {
                                    Text(
                                        "  •  unsaved changes",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = Color(0xFF9C27B0),
                                    )
                                }
                            }
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                                horizontalArrangement = Arrangement.spacedBy(12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Button(
                                    enabled = canUndo,
                                    onClick = { applyMutation(bridge.callAttr("undo").toString()) },
                                ) { Text("Undo") }
                                Button(
                                    enabled = canRedo,
                                    onClick = { applyMutation(bridge.callAttr("redo").toString()) },
                                ) { Text("Redo") }
                                // Everything less frequent than undo/redo
                                // lives behind one overflow menu instead of
                                // its own top-level button — the button row
                                // was already at four items with only Open/
                                // Save/debug-load, and every new action
                                // (border color, export, etc.) would have
                                // meant yet another button squeezed in.
                                Box {
                                    TextButton(onClick = { menuExpanded = true }) {
                                        Text("⋮ More")
                                    }
                                    DropdownMenu(
                                        expanded = menuExpanded,
                                        onDismissRequest = { menuExpanded = false },
                                    ) {
                                        DropdownMenuItem(
                                            text = { Text("Open .smmap…") },
                                            onClick = {
                                                menuExpanded = false
                                                openDocument.launch(arrayOf("*/*"))
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Save") },
                                            onClick = {
                                                menuExpanded = false
                                                saveCurrentMap()
                                            },
                                        )
                                        if (BuildConfig.DEBUG) {
                                            // Dev-only: sidesteps the system
                                            // file picker's UI for adb-driven
                                            // testing. Never shown in a
                                            // release build. Uses the app's
                                            // own external files dir, not
                                            // /sdcard/Download directly —
                                            // scoped storage blocks raw path
                                            // access there even for the
                                            // app's own reads/writes, which
                                            // is exactly why the real Open
                                            // action above goes through SAF
                                            // instead.
                                            DropdownMenuItem(
                                                text = { Text("Load test map") },
                                                onClick = {
                                                    menuExpanded = false
                                                    val f = File(getExternalFilesDir(null), "test.smmap")
                                                    loadFromPath(f.absolutePath)
                                                    currentDebugPath = f.absolutePath
                                                    currentUri = null
                                                },
                                            )
                                        }
                                    }
                                }
                            }
                        }
                        MindMapCanvas(
                            root = root,
                            expanded = expanded.value,
                            textMeasurer = textMeasurer,
                            onToggle = { id ->
                                expanded.value = if (id in expanded.value) {
                                    expanded.value - id
                                } else {
                                    expanded.value + id
                                }
                            },
                            // Was long-press — freed up for the new
                            // press-and-drag-to-move gesture below.
                            onOpenActions = { node -> actionTarget = node },
                            onReparent = { nodeId, newParentId ->
                                applyMutation(
                                    bridge.callAttr("reparent_node", nodeId, newParentId).toString()
                                )
                            },
                        )
                    }
                }

                // Long-press dialog: rename, add child, delete, move,
                // and a small preset-color styling row. One dialog for
                // all node actions rather than a separate gesture per
                // action — AlertDialog only gives two real buttons
                // (confirm/dismiss), so the extra actions live as their
                // own row inside `text`.
                val target = actionTarget
                if (target != null) {
                    var text by remember(target.id) { mutableStateOf(target.text) }
                    val isRoot = target.id == root.id
                    AlertDialog(
                        onDismissRequest = { actionTarget = null },
                        title = { Text("Node") },
                        text = {
                            Column {
                                OutlinedTextField(value = text, onValueChange = { text = it })
                                Row(
                                    modifier = Modifier.padding(top = 12.dp),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    TextButton(onClick = {
                                        // Real add path: core.commands.
                                        // AddNodeCommand via History — see
                                        // android_bridge.add_child().
                                        val json = JSONObject(
                                            bridge.callAttr("add_child", target.id, "New Node").toString()
                                        )
                                        applyMutation(json.toString())
                                        actionTarget = null
                                    }) { Text("Add Child") }
                                    if (!isRoot) {
                                        TextButton(onClick = {
                                            moveTarget = target
                                            actionTarget = null
                                        }) { Text("Move to…") }
                                    }
                                    if (!isRoot) {
                                        TextButton(onClick = {
                                            // MoveToTrashCommand — undo-capable,
                                            // see android_bridge.delete_node().
                                            applyMutation(bridge.callAttr("delete_node", target.id).toString())
                                            actionTarget = null
                                        }) { Text("Delete", color = MaterialTheme.colorScheme.error) }
                                    }
                                }
                                Row(
                                    modifier = Modifier.padding(top = 12.dp),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    for (hex in PRESET_COLORS) {
                                        Box(
                                            modifier = Modifier
                                                .size(32.dp)
                                                .background(parseHexColor(hex) ?: Color.Gray, CircleShape)
                                                .border(1.dp, Color.Black, CircleShape)
                                                .clickable {
                                                    applyMutation(
                                                        bridge.callAttr("set_fill_color", target.id, hex).toString()
                                                    )
                                                    actionTarget = null
                                                },
                                        )
                                    }
                                    // "Clear" back to the theme default (null).
                                    Box(
                                        modifier = Modifier
                                            .size(32.dp)
                                            .border(1.dp, Color.Black, CircleShape)
                                            .clickable {
                                                applyMutation(
                                                    bridge.callAttr("set_fill_color", target.id, null).toString()
                                                )
                                                actionTarget = null
                                            },
                                    ) { Text("×", modifier = Modifier.padding(6.dp)) }
                                }
                            }
                        },
                        confirmButton = {
                            TextButton(onClick = {
                                // Real edit path: core.commands.EditTextCommand
                                // via History (undo-capable), not a raw
                                // node.text mutation — see android_bridge's
                                // rename_node(). Re-measure/re-layout after,
                                // same as after *_structure(): the new text
                                // likely changed this node's own box size.
                                if (text != target.text) {
                                    applyMutation(bridge.callAttr("rename_node", target.id, text).toString())
                                }
                                actionTarget = null
                            }) { Text("Rename") }
                        },
                        dismissButton = {
                            TextButton(onClick = { actionTarget = null }) { Text("Cancel") }
                        },
                    )
                }

                // "Move to…" picker: a plain list rather than drag-and-drop.
                // Freeform dragging a node on this canvas would need to
                // steal single-finger gestures away from pan (which already
                // owns them via detectTransformGestures) based on whether
                // the touch started on a node — solvable, but only with
                // hand-rolled low-level pointer handling that's hard to
                // verify thoroughly without real multi-touch hardware. A
                // tap-a-target list is less flashy but uses the exact same
                // real ReparentNodeCommand and is trivial to get right.
                val moving = moveTarget
                if (moving != null) {
                    val excluded = remember(moving.id) {
                        mutableSetOf<String>().also { subtreeIds(moving, it) }
                    }
                    val candidates = remember(root, moving.id) {
                        val out = mutableListOf<MapNode>()
                        fun walk(n: MapNode) {
                            if (n.id !in excluded) out.add(n)
                            n.children.forEach { walk(it) }
                        }
                        walk(root)
                        out
                    }
                    AlertDialog(
                        onDismissRequest = { moveTarget = null },
                        title = { Text("Move \"${moving.text}\" to…") },
                        text = {
                            LazyColumn {
                                items(candidates) { candidate ->
                                    Text(
                                        candidate.text,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clickable {
                                                applyMutation(
                                                    bridge.callAttr(
                                                        "reparent_node", moving.id, candidate.id,
                                                    ).toString()
                                                )
                                                moveTarget = null
                                            }
                                            .padding(vertical = 12.dp),
                                    )
                                }
                            }
                        },
                        confirmButton = {},
                        dismissButton = {
                            TextButton(onClick = { moveTarget = null }) { Text("Cancel") }
                        },
                    )
                }
            }
        }
    }
}

private data class VisibleNode(val node: MapNode, val hasParent: MapNode?, val rect: Rect)

private const val NODE_PADDING_H = 24f
private const val NODE_PADDING_V = 16f
private val canvasTextStyle = TextStyle(fontSize = 14.sp, color = Color.Black)

/** Flattens the tree into world-space boxes, skipping subtrees under a
 * collapsed node. Shared by drawing AND tap hit-testing so they can never
 * disagree about where a node actually is. */
private fun computeVisible(
    node: MapNode,
    parent: MapNode?,
    expanded: Set<String>,
    measure: (String) -> androidx.compose.ui.geometry.Size,
    out: MutableList<VisibleNode>,
) {
    val textSize = measure(node.text)
    val w = textSize.width + NODE_PADDING_H * 2
    val h = textSize.height + NODE_PADDING_V * 2
    // node.x/node.y are the node's TOP-LEFT corner, not its center — see
    // core.layout._layout_h_children's own docstring ("anchor.x/anchor.y
    // are the anchor node's TOP-LEFT"). Treating them as a center here
    // was a real bug: it silently shifted every box by half its own
    // size, which still LOOKED like a plausible fan-out tree but
    // produced wrong spacing (a visible root/child overlap on a wider
    // map) that briefly looked like a layout.py bug until the
    // convention mismatch was traced back to this line.
    val rect = Rect(
        left = node.x, top = node.y,
        right = node.x + w, bottom = node.y + h,
    )
    out.add(VisibleNode(node, parent, rect))
    if (node.children.isEmpty() || node.id !in expanded) return
    for (child in node.children) {
        computeVisible(child, node, expanded, measure, out)
    }
}

@androidx.compose.runtime.Composable
private fun MindMapCanvas(
    root: MapNode,
    expanded: Set<String>,
    textMeasurer: androidx.compose.ui.text.TextMeasurer,
    onToggle: (String) -> Unit,
    // Was long-press — moved to double-tap to free long-press up for
    // press-and-drag-to-move below (detectDragGesturesAfterLongPress
    // and "open the node dialog on long-press" both want the same
    // gesture start, so one of them had to move).
    onOpenActions: (MapNode) -> Unit,
    onReparent: (nodeId: String, newParentId: String) -> Unit,
) {
    val textStyle = canvasTextStyle

    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }

    // Drag-to-move state. dragScreenDelta accumulates raw pointer motion
    // (screen pixels); converted to world units (÷ scale) only where it's
    // actually used, since world-space distances scale with zoom but raw
    // finger motion doesn't.
    var draggingNodeId by remember { mutableStateOf<String?>(null) }
    var dragScreenDelta by remember { mutableStateOf(Offset.Zero) }
    var dropTargetId by remember { mutableStateOf<String?>(null) }

    val visible = remember(root, expanded) {
        val out = mutableListOf<VisibleNode>()
        computeVisible(root, null, expanded, { text ->
            textMeasurer.measure(text, textStyle).size.let {
                androidx.compose.ui.geometry.Size(it.width.toFloat(), it.height.toFloat())
            }
        }, out)
        out
    }

    fun worldPoint(screenOffset: Offset, canvasSize: androidx.compose.ui.unit.IntSize): Offset {
        val centerX = canvasSize.width / 2f + offset.x
        val centerY = canvasSize.height / 2f + offset.y
        return Offset((screenOffset.x - centerX) / scale, (screenOffset.y - centerY) / scale)
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                detectTransformGestures { _, pan, zoom, _ ->
                    // Only pans/zooms empty space — a touch that starts on
                    // a node is claimed by the drag-to-move detector below
                    // instead (see its own onDragStart). Compose still
                    // routes the initial down here too, so without this
                    // guard a node-drag would ALSO pan the canvas under it.
                    if (draggingNodeId == null) {
                        scale = (scale * zoom).coerceIn(0.2f, 4f)
                        offset += pan
                    }
                }
            }
            .pointerInput(visible, scale, offset) {
                // Shared by both gestures: the same screen-to-world inverse
                // of the transform drawing applies below (translate to
                // center + pan, then scale), so tap and double-tap can
                // never disagree about which node they landed on.
                fun hitTest(screenOffset: Offset): VisibleNode? {
                    val world = worldPoint(screenOffset, size)
                    return visible.lastOrNull { it.rect.contains(world) }
                }
                detectTapGestures(
                    onTap = { tapOffset ->
                        val hit = hitTest(tapOffset)
                        if (hit != null && hit.node.children.isNotEmpty()) {
                            onToggle(hit.node.id)
                        }
                    },
                    onDoubleTap = { tapOffset ->
                        hitTest(tapOffset)?.let { onOpenActions(it.node) }
                    },
                )
            }
            .pointerInput(visible, scale, offset, root) {
                fun hitTest(screenOffset: Offset): VisibleNode? {
                    val world = worldPoint(screenOffset, size)
                    return visible.lastOrNull { it.rect.contains(world) }
                }
                detectDragGesturesAfterLongPress(
                    onDragStart = { startOffset ->
                        val hit = hitTest(startOffset)
                        // Root has no parent to move it out of — dragging
                        // it would have nowhere valid to go.
                        if (hit != null && hit.node.id != root.id) {
                            draggingNodeId = hit.node.id
                            dragScreenDelta = Offset.Zero
                            dropTargetId = null
                        }
                    },
                    onDrag = { change, dragAmount ->
                        if (draggingNodeId == null) return@detectDragGesturesAfterLongPress
                        change.consume()
                        dragScreenDelta += dragAmount
                        val draggedRect = visible.first { it.node.id == draggingNodeId }.rect
                        val draggedCenterNow = draggedRect.center + dragScreenDelta / scale
                        // A node can't be dropped onto itself or its own
                        // descendants — computed fresh each drag update
                        // since which node is "self" doesn't change but
                        // this is cheap enough not to bother memoizing.
                        val excluded = mutableSetOf<String>()
                        visible.first { it.node.id == draggingNodeId }
                            .let { subtreeIds(it.node, excluded) }
                        dropTargetId = visible.lastOrNull {
                            it.node.id !in excluded && it.rect.contains(draggedCenterNow)
                        }?.node?.id
                    },
                    onDragEnd = {
                        val nodeId = draggingNodeId
                        val target = dropTargetId
                        if (nodeId != null && target != null && target != nodeId) {
                            onReparent(nodeId, target)
                        }
                        draggingNodeId = null
                        dropTargetId = null
                        dragScreenDelta = Offset.Zero
                    },
                    onDragCancel = {
                        draggingNodeId = null
                        dropTargetId = null
                        dragScreenDelta = Offset.Zero
                    },
                )
            },
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            translate(left = size.width / 2f + offset.x, top = size.height / 2f + offset.y) {
                scale(scale, pivot = Offset.Zero) {
                    // Connectors first so node boxes paint over the ends.
                    // Centers come from each node's own computed rect
                    // (id-keyed lookup), not raw node.x/y — those are
                    // top-left corners, not centers (see computeVisible).
                    val rectById = visible.associate { it.node.id to it.rect }
                    for (v in visible) {
                        val parent = v.hasParent ?: continue
                        val parentCenter = rectById.getValue(parent.id).center
                        val childCenter = if (v.node.id == draggingNodeId) {
                            v.rect.center + dragScreenDelta / scale
                        } else {
                            v.rect.center
                        }
                        drawLine(
                            color = Color(0xFF9575CD),
                            start = parentCenter,
                            end = childCenter,
                            strokeWidth = 2f / scale,
                        )
                    }
                    for (v in visible) {
                        val isRoot = v.hasParent == null
                        val isDragging = v.node.id == draggingNodeId
                        val isDropTarget = v.node.id == dropTargetId
                        // The dragged box visually follows the finger;
                        // everything else stays put until drop.
                        val drawRect = if (isDragging) {
                            v.rect.translate(dragScreenDelta / scale)
                        } else {
                            v.rect
                        }
                        val fill = v.node.fillColor
                            ?: (if (isRoot) Color(0xFF673AB7) else Color(0xFFEDE7F6))
                        drawRoundRect(
                            color = fill,
                            topLeft = drawRect.topLeft,
                            size = drawRect.size,
                            cornerRadius = androidx.compose.ui.geometry.CornerRadius(12f, 12f),
                            alpha = if (isDragging) 0.85f else 1f,
                        )
                        val border = v.node.borderColor
                        if (border != null) {
                            drawRoundRect(
                                color = border,
                                topLeft = drawRect.topLeft,
                                size = drawRect.size,
                                cornerRadius = androidx.compose.ui.geometry.CornerRadius(12f, 12f),
                                style = androidx.compose.ui.graphics.drawscope.Stroke(width = 3f / scale),
                            )
                        }
                        // A valid drop target gets its own highlight ring
                        // regardless of its own border color, so it reads
                        // clearly even on a node with no border set.
                        if (isDropTarget) {
                            drawRoundRect(
                                color = Color(0xFF2E7D32),
                                topLeft = drawRect.topLeft,
                                size = drawRect.size,
                                cornerRadius = androidx.compose.ui.geometry.CornerRadius(12f, 12f),
                                style = androidx.compose.ui.graphics.drawscope.Stroke(width = 4f / scale),
                            )
                        }
                        // White text reads on both the purple root default
                        // AND any preset fill color (all mid-to-dark); a
                        // custom VERY light fill would need dark text
                        // instead, but none of the presets are light enough
                        // to need that yet.
                        val textColor = if (isRoot || v.node.fillColor != null) Color.White else Color.Black
                        drawText(
                            textMeasurer = textMeasurer,
                            text = v.node.text,
                            topLeft = Offset(
                                drawRect.left + NODE_PADDING_H,
                                drawRect.top + NODE_PADDING_V,
                            ),
                            style = textStyle.copy(color = textColor),
                        )
                    }
                }
            }
        }
    }
}
