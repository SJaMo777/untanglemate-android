package com.syntheticcodelab.untanglemate

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.clickable
import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
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
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.isSecondaryPressed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneOffset
import java.time.format.TextStyle as JavaTextStyle
import java.util.Locale
import kotlin.math.roundToInt
import kotlinx.coroutines.withTimeoutOrNull

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
    // "YYYY-MM-DD" or null — only the two todo_* fields a plain due-date
    // list needs; todo_priority/todo_recurrence have no Android UI yet.
    val todoMarked: Boolean,
    val todoDueAt: String?,
    // 1 (most urgent) .. 5 (least), or null — node_item.py's general
    // priority_level badge, independent of todo_priority.
    val priorityLevel: Int?,
    // node_item.py's amber "T" badge — this node names its subtree.
    val isTopic: Boolean,
    val children: List<MapNode>,
)

/** One row of the Calendar dialog's due-date list, parsed from
 * android_bridge.list_todos(). */
data class TodoItem(val id: String, val text: String, val dueAt: String?)

private fun parseTodos(json: String): List<TodoItem> {
    val array = org.json.JSONArray(json)
    return (0 until array.length()).map { i ->
        val obj = array.getJSONObject(i)
        TodoItem(
            id = obj.getString("id"),
            text = obj.getString("text"),
            dueAt = if (obj.isNull("dueAt")) null else obj.getString("dueAt"),
        )
    }
}

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
        todoMarked = obj.optBoolean("todoMarked", false),
        todoDueAt = if (obj.isNull("todoDueAt")) null else obj.getString("todoDueAt"),
        priorityLevel = if (obj.isNull("priorityLevel")) null else obj.getInt("priorityLevel"),
        isTopic = obj.optBoolean("isTopic", false),
        children = children,
    )
}

/** Looks up a node by id from the root — used by the header's Edit menu,
 * which only carries the selected id (not the MapNode itself, so it stays
 * correct across recompositions after an edit changes the tree). */
private fun findMapNode(node: MapNode, id: String): MapNode? {
    if (node.id == id) return node
    for (child in node.children) {
        findMapNode(child, id)?.let { return it }
    }
    return null
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

    @OptIn(ExperimentalMaterial3Api::class)
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
            var dueDateTarget by remember { mutableStateOf<MapNode?>(null) }
            var calendarOpen by remember { mutableStateOf(false) }
            var todos by remember { mutableStateOf(listOf<TodoItem>()) }
            var canUndo by remember { mutableStateOf(false) }
            var canRedo by remember { mutableStateOf(false) }
            var isDirty by remember { mutableStateOf(false) }
            var fileMenuOpen by remember { mutableStateOf(false) }
            var editMenuOpen by remember { mutableStateOf(false) }
            // Hoisted up from the canvas (rather than living as the
            // canvas's own local state) so the Edit menu — which lives in
            // this header, not inside MindMapCanvas — can act on whichever
            // node a tap last selected, the same way Windows's Edit menu
            // acts on canvas.selected_node.
            var selectedNodeId by remember { mutableStateOf<String?>(null) }

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

            fun startNewMap() {
                val structureJson = bridge.callAttr("new_map_structure").toString()
                title = JSONObject(structureJson).getString("title")
                root = applyStructureAndLayout(structureJson)
                expanded.value = setOf(root.id)
                currentUri = null
                currentDebugPath = null
                selectedNodeId = null
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
                            // A real top menu bar, like Windows's File/Edit —
                            // Edit acts on whichever node is currently
                            // selected (selectedNodeId), the same way
                            // Windows's Edit menu acts on canvas.selected_node.
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box {
                                    TextButton(onClick = { fileMenuOpen = true }) {
                                        Text("File")
                                    }
                                    DropdownMenu(
                                        expanded = fileMenuOpen,
                                        onDismissRequest = { fileMenuOpen = false },
                                    ) {
                                        DropdownMenuItem(
                                            text = { Text("New Map") },
                                            onClick = {
                                                fileMenuOpen = false
                                                startNewMap()
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Open .smmap…") },
                                            onClick = {
                                                fileMenuOpen = false
                                                openDocument.launch(arrayOf("*/*"))
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Save") },
                                            onClick = {
                                                fileMenuOpen = false
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
                                                    fileMenuOpen = false
                                                    val f = File(getExternalFilesDir(null), "test.smmap")
                                                    loadFromPath(f.absolutePath)
                                                    currentDebugPath = f.absolutePath
                                                    currentUri = null
                                                },
                                            )
                                        }
                                    }
                                }
                                Box {
                                    TextButton(onClick = { editMenuOpen = true }) {
                                        Text("Edit")
                                    }
                                    val selectedNode = selectedNodeId?.let { findMapNode(root, it) }
                                    DropdownMenu(
                                        expanded = editMenuOpen,
                                        onDismissRequest = { editMenuOpen = false },
                                    ) {
                                        DropdownMenuItem(
                                            text = { Text("Undo") },
                                            enabled = canUndo,
                                            onClick = {
                                                editMenuOpen = false
                                                applyMutation(bridge.callAttr("undo").toString())
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Redo") },
                                            enabled = canRedo,
                                            onClick = {
                                                editMenuOpen = false
                                                applyMutation(bridge.callAttr("redo").toString())
                                            },
                                        )
                                        HorizontalDivider()
                                        DropdownMenuItem(
                                            text = { Text("Add Child") },
                                            onClick = {
                                                editMenuOpen = false
                                                val targetId = selectedNodeId ?: root.id
                                                val json = JSONObject(
                                                    bridge.callAttr("add_child", targetId, "New Node").toString()
                                                )
                                                applyMutation(json.toString())
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Edit Text / Style…") },
                                            enabled = selectedNode != null,
                                            onClick = {
                                                editMenuOpen = false
                                                selectedNode?.let { actionTarget = it }
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Move to…") },
                                            enabled = selectedNode != null && selectedNode.id != root.id,
                                            onClick = {
                                                editMenuOpen = false
                                                selectedNode?.let { moveTarget = it }
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Delete", color = MaterialTheme.colorScheme.error) },
                                            enabled = selectedNode != null && selectedNode.id != root.id,
                                            onClick = {
                                                editMenuOpen = false
                                                selectedNode?.let {
                                                    applyMutation(bridge.callAttr("delete_node", it.id).toString())
                                                    selectedNodeId = null
                                                }
                                            },
                                        )
                                        HorizontalDivider()
                                        DropdownMenuItem(
                                            text = { Text("Toggle Collapse") },
                                            enabled = selectedNode != null && selectedNode.children.isNotEmpty(),
                                            onClick = {
                                                editMenuOpen = false
                                                selectedNode?.let { node ->
                                                    expanded.value = if (node.id in expanded.value) {
                                                        expanded.value - node.id
                                                    } else {
                                                        expanded.value + node.id
                                                    }
                                                }
                                            },
                                        )
                                        DropdownMenuItem(
                                            text = { Text("Deselect") },
                                            enabled = selectedNode != null,
                                            onClick = {
                                                editMenuOpen = false
                                                selectedNodeId = null
                                            },
                                        )
                                        HorizontalDivider()
                                        DropdownMenuItem(
                                            text = { Text("Set Due Date…") },
                                            enabled = selectedNode != null,
                                            onClick = {
                                                editMenuOpen = false
                                                selectedNode?.let { dueDateTarget = it }
                                            },
                                        )
                                    }
                                }
                                Box {
                                    TextButton(onClick = {
                                        todos = parseTodos(bridge.callAttr("list_todos").toString())
                                        calendarOpen = true
                                    }) {
                                        Text("Calendar")
                                    }
                                }
                            }

                            // The icon toolbar Windows calls its "Menu Bar"
                            // (menu_bar.py's CustomMenuBar, grouped dark
                            // icon frames below the text File/Edit/View/…
                            // bar). Windows's version is a large, per-map
                            // customizable toolbar with dozens of buttons
                            // for features (attachments, tags, priorities,
                            // layout recall…) that don't exist here yet —
                            // this mirrors its grouped-icon-frame LOOK using
                            // only the functions this app actually has, the
                            // same actions as the File/Edit dropdowns above,
                            // just one tap away instead of two.
                            val selectedNode = selectedNodeId?.let { findMapNode(root, it) }
                            // Colors pulled straight from the map's own
                            // palette (root node fill, connector line color)
                            // rather than a generic dark grey — the same
                            // idea as menu_bar.py's own comment: "buttons
                            // are painted like nodes... so the bar reads as
                            // part of the map rather than a strip of
                            // unrelated colours."
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(top = 8.dp)
                                    .background(Color(0xFF3B2E5A), RoundedCornerShape(8.dp))
                                    .padding(8.dp),
                                horizontalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                ToolbarGroup("History") {
                                    ToolbarIconButton("↺", enabled = canUndo) {
                                        applyMutation(bridge.callAttr("undo").toString())
                                    }
                                    ToolbarIconButton("↻", enabled = canRedo) {
                                        applyMutation(bridge.callAttr("redo").toString())
                                    }
                                }
                                ToolbarGroup("File") {
                                    ToolbarIconButton("🆕") { startNewMap() }
                                    ToolbarIconButton("📂") { openDocument.launch(arrayOf("*/*")) }
                                    ToolbarIconButton("💾") { saveCurrentMap() }
                                }
                                ToolbarGroup("Node Actions") {
                                    ToolbarIconButton("➕") {
                                        val targetId = selectedNodeId ?: root.id
                                        val json = JSONObject(
                                            bridge.callAttr("add_child", targetId, "New Node").toString()
                                        )
                                        applyMutation(json.toString())
                                    }
                                    ToolbarIconButton("✏", enabled = selectedNode != null) {
                                        selectedNode?.let { actionTarget = it }
                                    }
                                    ToolbarIconButton(
                                        "📤",
                                        enabled = selectedNode != null && selectedNode.id != root.id,
                                    ) {
                                        selectedNode?.let { moveTarget = it }
                                    }
                                    ToolbarIconButton(
                                        "🗑",
                                        enabled = selectedNode != null && selectedNode.id != root.id,
                                    ) {
                                        selectedNode?.let {
                                            applyMutation(bridge.callAttr("delete_node", it.id).toString())
                                            selectedNodeId = null
                                        }
                                    }
                                    ToolbarIconButton(
                                        "▦",
                                        enabled = selectedNode != null && selectedNode.children.isNotEmpty(),
                                    ) {
                                        selectedNode?.let { node ->
                                            expanded.value = if (node.id in expanded.value) {
                                                expanded.value - node.id
                                            } else {
                                                expanded.value + node.id
                                            }
                                        }
                                    }
                                    ToolbarIconButton("✕", enabled = selectedNode != null) {
                                        selectedNodeId = null
                                    }
                                }
                                ToolbarGroup("Calendar") {
                                    ToolbarIconButton("🗓", enabled = selectedNode != null) {
                                        selectedNode?.let { dueDateTarget = it }
                                    }
                                    ToolbarIconButton("📅") {
                                        todos = parseTodos(bridge.callAttr("list_todos").toString())
                                        calendarOpen = true
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
                            onOpenActions = { node -> actionTarget = node },
                            onReparent = { nodeId, newParentId ->
                                applyMutation(
                                    bridge.callAttr("reparent_node", nodeId, newParentId).toString()
                                )
                            },
                            // Right-click (mouse secondary button) or tap-
                            // then-hold (touch) on a node opens the same
                            // full "Node" dialog as triple-tap (onOpenActions
                            // above) — a custom quick-menu popup used to
                            // live here instead, but its items weren't
                            // reliably clickable in every environment
                            // (arrow-key navigation worked, direct clicks on
                            // items didn't), so this reuses the dialog
                            // that's already proven reliable everywhere.
                            // Right-click/hold on EMPTY canvas has no node
                            // to open a dialog for, so it just performs its
                            // one possible action directly.
                            onAddChildToRoot = {
                                val json = JSONObject(
                                    bridge.callAttr("add_child", root.id, "New Node").toString()
                                )
                                applyMutation(json.toString())
                            },
                            // Hoisted so the header's Edit menu (outside the
                            // canvas) can see and act on the same selection
                            // a tap sets.
                            selectedNodeId = selectedNodeId,
                            onSelect = { id -> selectedNodeId = id },
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
                                // Same actions as the hold-down/right-click
                                // context menu's ToDo items, but reachable
                                // through only plain taps (this dialog also
                                // opens via triple-tap or the toolbar/Edit
                                // menu) — no press-and-hold timing involved,
                                // for anyone whose hold-down gesture isn't
                                // registering reliably (e.g. a mouse on the
                                // emulator rather than a real touchscreen).
                                Row(
                                    modifier = Modifier.padding(top = 12.dp),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    TextButton(onClick = {
                                        applyMutation(
                                            bridge.callAttr(
                                                "set_todo", target.id, !target.todoMarked, target.todoDueAt,
                                            ).toString()
                                        )
                                        actionTarget = null
                                    }) {
                                        Text(if (target.todoMarked) "Unmark as ToDo" else "Mark as ToDo")
                                    }
                                    TextButton(onClick = {
                                        dueDateTarget = target
                                        actionTarget = null
                                    }) { Text("Set Due Date…") }
                                }
                                // Priority (1 = most urgent .. 5 = least),
                                // same color scale as priority_panel.py's
                                // _PRIORITY_COLOR, via the real
                                // SetPriorityLevelCommand (undo-capable).
                                Row(
                                    modifier = Modifier.padding(top = 12.dp),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    val priorityColors = mapOf(
                                        1 to Color(0xFFEF4444), 2 to Color(0xFFF97316),
                                        3 to Color(0xFFEAB308), 4 to Color(0xFF84CC16),
                                        5 to Color(0xFF3B82F6),
                                    )
                                    for ((level, levelColor) in priorityColors) {
                                        Box(
                                            modifier = Modifier
                                                .size(32.dp)
                                                .background(levelColor, CircleShape)
                                                .border(
                                                    if (target.priorityLevel == level) 3.dp else 1.dp,
                                                    Color.Black,
                                                    CircleShape,
                                                )
                                                .clickable {
                                                    applyMutation(
                                                        bridge.callAttr("set_priority", target.id, level).toString()
                                                    )
                                                    actionTarget = null
                                                },
                                            contentAlignment = Alignment.Center,
                                        ) { Text("$level", color = Color.White) }
                                    }
                                    Box(
                                        modifier = Modifier
                                            .size(32.dp)
                                            .border(1.dp, Color.Black, CircleShape)
                                            .clickable {
                                                applyMutation(
                                                    bridge.callAttr("set_priority", target.id, null).toString()
                                                )
                                                actionTarget = null
                                            },
                                        contentAlignment = Alignment.Center,
                                    ) { Text("×") }
                                }
                                // Topic — amber "T" badge, direct mutation
                                // (no undo), matching Windows's own
                                // toggle_topic_on_selected(): "topic marks
                                // are presentation metadata, like
                                // bookmark/view-lock".
                                TextButton(
                                    onClick = {
                                        applyMutation(bridge.callAttr("toggle_topic", target.id).toString())
                                        actionTarget = null
                                    },
                                    modifier = Modifier.padding(top = 4.dp),
                                ) {
                                    Text(if (target.isTopic) "Unmark as Topic" else "Mark as Topic")
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

                // "Set Due Date…": a real Material3 DatePicker. Only the
                // final "YYYY-MM-DD" string matters to the bridge — it's
                // forwarded verbatim to core.commands.SetTodoStateCommand,
                // which stores it unparsed until something reads it with
                // datetime.fromisoformat, same as Windows — the picker's
                // own UTC-epoch-millis representation just needs
                // converting to that string on Save.
                val dueTarget = dueDateTarget
                if (dueTarget != null) {
                    val initialMillis = dueTarget.todoDueAt?.let {
                        runCatching {
                            LocalDate.parse(it).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
                        }.getOrNull()
                    }
                    val datePickerState = rememberDatePickerState(initialSelectedDateMillis = initialMillis)
                    DatePickerDialog(
                        onDismissRequest = { dueDateTarget = null },
                        confirmButton = {
                            TextButton(
                                enabled = datePickerState.selectedDateMillis != null,
                                onClick = {
                                    val millis = datePickerState.selectedDateMillis
                                    if (millis != null) {
                                        val due = Instant.ofEpochMilli(millis)
                                            .atZone(ZoneOffset.UTC).toLocalDate().toString()
                                        applyMutation(
                                            bridge.callAttr("set_todo", dueTarget.id, true, due).toString()
                                        )
                                    }
                                    dueDateTarget = null
                                },
                            ) { Text("Save") }
                        },
                        dismissButton = {
                            Row {
                                if (dueTarget.todoDueAt != null) {
                                    TextButton(onClick = {
                                        applyMutation(
                                            bridge.callAttr("set_todo", dueTarget.id, false, null).toString()
                                        )
                                        dueDateTarget = null
                                    }) { Text("Clear") }
                                }
                                TextButton(onClick = { dueDateTarget = null }) { Text("Cancel") }
                            }
                        },
                    ) {
                        DatePicker(state = datePickerState)
                    }
                }

                // Calendar: a real month grid, like Windows's CalendarPanel
                // (calendar_panel.py's _render_month) — weekday header,
                // days laid out 7-per-row including the leading/trailing
                // days of adjacent months, a dot on any day with a due
                // item, tap a day to see what's due and jump to it. Not
                // ported: week view, review scheduling, recurrence, and
                // Google Calendar sync — no Android equivalent yet.
                if (calendarOpen) {
                    CalendarMonthDialog(
                        todos = todos,
                        onSelectNode = { id -> selectedNodeId = id },
                        onDismiss = { calendarOpen = false },
                    )
                }
            }
        }
    }
}

/** One labeled, framed cluster of icon buttons — the Android equivalent of
 * a group frame in Windows's CustomMenuBar (menu_bar.py), which paints a
 * small caption above a dark rounded frame of QToolButtons. */
@androidx.compose.runtime.Composable
private fun ToolbarGroup(
    title: String,
    content: @androidx.compose.runtime.Composable RowScope.() -> Unit,
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            title,
            style = MaterialTheme.typography.labelSmall,
            color = Color(0xFFD1C4E9),
        )
        Row(
            modifier = Modifier
                .padding(top = 2.dp)
                // The map's own root-node purple (see MindMapCanvas's
                // drawing loop) — the frame reads as one of the map's own
                // boxes instead of unrelated toolbar chrome.
                .background(Color(0xFF673AB7), RoundedCornerShape(6.dp))
                .padding(4.dp),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            content = content,
        )
    }
}

/** One icon button on the toolbar. Plain glyph text rather than a Material
 * icon font — this project has no material-icons-extended dependency, and
 * the Windows bar itself is emoji glyphs (see menu_bar.py's own header
 * comment on `_MB_GLYPH_PX`), so a Unicode glyph is the closer match
 * anyway. */
@androidx.compose.runtime.Composable
private fun ToolbarIconButton(glyph: String, enabled: Boolean = true, onClick: () -> Unit) {
    androidx.compose.material3.IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.size(36.dp),
    ) {
        Text(
            glyph,
            fontSize = 18.sp,
            // Disabled uses the same purple the canvas draws connector
            // lines with (see MindMapCanvas), rather than a flat grey.
            color = if (enabled) Color.White else Color(0xFF9575CD),
        )
    }
}

/** A real month-grid calendar, matching Windows's CalendarPanel
 * (calendar_panel.py's _render_month): month/year header with prev/next
 * navigation, a weekday header row, then a 7-column grid of every day in
 * the month plus the leading/trailing days of the adjacent months so
 * every week row is full — the same `itermonthdates`-style layout, done
 * with java.time instead of Python's `calendar` module. */
@androidx.compose.runtime.Composable
private fun CalendarMonthDialog(
    todos: List<TodoItem>,
    onSelectNode: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var viewMonth by remember { mutableStateOf(YearMonth.now()) }
    var selectedDay by remember { mutableStateOf<LocalDate?>(LocalDate.now()) }

    val itemsByDate = remember(todos) {
        todos.mapNotNull { item ->
            item.dueAt?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.let { it to item }
        }.groupBy({ it.first }, { it.second })
    }

    androidx.compose.ui.window.Dialog(onDismissRequest = onDismiss) {
        Surface(shape = RoundedCornerShape(16.dp), color = Color(0xFFF3EEFB)) {
            Column(modifier = Modifier.padding(16.dp).width(340.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(onClick = { viewMonth = viewMonth.minusMonths(1) }) { Text("◀") }
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            "${viewMonth.month.getDisplayName(JavaTextStyle.FULL, Locale.getDefault())} ${viewMonth.year}",
                            style = MaterialTheme.typography.titleMedium,
                        )
                        TextButton(onClick = {
                            viewMonth = YearMonth.now()
                            selectedDay = LocalDate.now()
                        }) { Text("Today", style = MaterialTheme.typography.labelSmall) }
                    }
                    TextButton(onClick = { viewMonth = viewMonth.plusMonths(1) }) { Text("▶") }
                }
                Row(modifier = Modifier.fillMaxWidth()) {
                    for (name in listOf("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")) {
                        Text(
                            name,
                            modifier = Modifier.weight(1f),
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                            style = MaterialTheme.typography.labelSmall,
                            color = Color(0xFF9575CD),
                        )
                    }
                }
                val firstOfMonth = viewMonth.atDay(1)
                // DayOfWeek.value is 1=Monday..7=Sunday, matching the Mo-Su
                // header above — how many cells to back up to reach the
                // Monday on/before the 1st.
                val leading = firstOfMonth.dayOfWeek.value - 1
                val totalDays = leading + viewMonth.lengthOfMonth()
                val totalCells = ((totalDays + 6) / 7) * 7
                val gridStart = firstOfMonth.minusDays(leading.toLong())
                val today = LocalDate.now()
                for (row in 0 until totalCells / 7) {
                    Row(modifier = Modifier.fillMaxWidth()) {
                        for (col in 0..6) {
                            val day = gridStart.plusDays((row * 7 + col).toLong())
                            val inMonth = day.month == viewMonth.month
                            val hasItems = itemsByDate.containsKey(day)
                            val isSelected = day == selectedDay
                            val isToday = day == today
                            Box(
                                modifier = Modifier
                                    .weight(1f)
                                    .aspectRatio(1f)
                                    .padding(1.dp)
                                    .background(
                                        when {
                                            isSelected -> Color(0xFF673AB7)
                                            isToday -> Color(0xFFD1C4E9)
                                            else -> Color.Transparent
                                        },
                                        RoundedCornerShape(6.dp),
                                    )
                                    .clickable { selectedDay = day },
                                contentAlignment = Alignment.Center,
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text(
                                        "${day.dayOfMonth}",
                                        fontSize = 13.sp,
                                        color = when {
                                            isSelected -> Color.White
                                            !inMonth -> Color(0xFFC5B8E0)
                                            else -> Color.Black
                                        },
                                    )
                                    if (hasItems) {
                                        Box(
                                            modifier = Modifier
                                                .size(5.dp)
                                                .background(
                                                    if (isSelected) Color.White else Color(0xFF673AB7),
                                                    CircleShape,
                                                ),
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
                HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
                val dayItems = selectedDay?.let { itemsByDate[it] } ?: emptyList()
                Text(
                    selectedDay?.toString() ?: "",
                    style = MaterialTheme.typography.labelSmall,
                    color = Color(0xFF9575CD),
                )
                if (dayItems.isEmpty()) {
                    Text("Nothing due", modifier = Modifier.padding(top = 4.dp))
                } else {
                    Column {
                        for (item in dayItems) {
                            Text(
                                item.text,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable { onSelectNode(item.id); onDismiss() }
                                    .padding(vertical = 6.dp),
                            )
                        }
                    }
                }
                TextButton(
                    onClick = onDismiss,
                    modifier = Modifier.align(Alignment.End).padding(top = 4.dp),
                ) { Text("Close") }
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
    onAddChildToRoot: () -> Unit,
    selectedNodeId: String?,
    onSelect: (String?) -> Unit,
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
            // Mouse right-click (Chromebook / DeX / a tablet with a mouse
            // attached — Android has supported this for years, it's just
            // rarely used from touch-only devices). Placed FIRST in the
            // modifier chain so it sees the Initial pass before the pan/
            // zoom, tap, and drag detectors below get the Main pass; on a
            // right-click it consumes the down change, which makes their
            // requireUnconsumed-by-default awaitFirstDown() ignore it —
            // touch input never sets isSecondaryPressed, so this never
            // affects an actual finger tap/drag/pinch, only a real mouse's
            // right button.
            .pointerInput(visible, scale, offset) {
                fun hitTest(screenOffset: Offset): VisibleNode? {
                    val world = worldPoint(screenOffset, size)
                    return visible.lastOrNull { it.rect.contains(world) }
                }
                awaitEachGesture {
                    val event = awaitPointerEvent(PointerEventPass.Initial)
                    if (event.type == PointerEventType.Press && event.buttons.isSecondaryPressed) {
                        val position = event.changes.first().position
                        val hit = hitTest(position)?.node
                        if (hit != null) onOpenActions(hit) else onAddChildToRoot()
                        event.changes.forEach { it.consume() }
                    }
                }
            }
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
            // One hand-rolled detector covers the whole touch gesture set,
            // since Compose's built-in detectTapGestures only distinguishes
            // single vs. double tap and can't express "third tap" or "tap,
            // then hold" on its own:
            //   1 tap            -> select (a highlight ring, display only)
            //   2 taps           -> toggle expand/collapse
            //   3 taps           -> edit name (opens the same dialog as
            //                       the touch-context-menu's "Rename/Style…")
            //   hold from cold   -> drag to move/reparent
            //   tap, then hold   -> the touch equivalent of a mouse
            //                       right-click: the same context menu
            .pointerInput(visible, scale, offset, root) {
                fun hitTest(screenOffset: Offset): VisibleNode? {
                    val world = worldPoint(screenOffset, size)
                    return visible.lastOrNull { it.rect.contains(world) }
                }
                awaitEachGesture {
                    var down = awaitFirstDown()
                    // Resolved once, from the very first touch of the
                    // cluster — later taps in the same cluster are assumed
                    // to be hitting the same node a real finger is aiming
                    // at, rather than re-hit-testing (and possibly
                    // disagreeing) on every intermediate tap.
                    val hitNode = hitTest(down.position)?.node
                    var tapCount = 0
                    var resolved = false

                    while (!resolved) {
                        tapCount++
                        val up = withTimeoutOrNull(viewConfiguration.longPressTimeoutMillis) {
                            waitForUpOrCancellation()
                        }

                        if (up == null) {
                            // Still down past the long-press threshold.
                            if (tapCount == 1) {
                                // Held from cold, no prior tap this cluster
                                // -> drag to move. Root has no parent to
                                // move it out of, so it's not draggable.
                                if (hitNode != null && hitNode.id != root.id) {
                                    draggingNodeId = hitNode.id
                                    dragScreenDelta = Offset.Zero
                                    dropTargetId = null
                                    while (true) {
                                        val event = awaitPointerEvent()
                                        val change =
                                            event.changes.firstOrNull { it.id == down.id }
                                                ?: break
                                        if (!change.pressed) break
                                        change.consume()
                                        dragScreenDelta += change.positionChange()
                                        val draggedRect =
                                            visible.first { it.node.id == draggingNodeId }.rect
                                        val draggedCenterNow =
                                            draggedRect.center + dragScreenDelta / scale
                                        // A node can't be dropped onto itself
                                        // or its own descendants — computed
                                        // fresh each move since which node is
                                        // "self" doesn't change, but this is
                                        // cheap enough not to bother
                                        // memoizing.
                                        val excluded = mutableSetOf<String>()
                                        visible.first { it.node.id == draggingNodeId }
                                            .let { subtreeIds(it.node, excluded) }
                                        dropTargetId = visible.lastOrNull {
                                            it.node.id !in excluded &&
                                                it.rect.contains(draggedCenterNow)
                                        }?.node?.id
                                    }
                                    val nodeId = draggingNodeId
                                    val target = dropTargetId
                                    if (nodeId != null && target != null && target != nodeId) {
                                        onReparent(nodeId, target)
                                    }
                                    draggingNodeId = null
                                    dropTargetId = null
                                    dragScreenDelta = Offset.Zero
                                }
                            } else {
                                // A tap (or two) already landed this
                                // cluster, and now the finger is holding
                                // instead of releasing quickly again — the
                                // touch equivalent of a mouse right-click.
                                if (hitNode != null) onOpenActions(hitNode) else onAddChildToRoot()
                                // Drain the rest of this press so releasing
                                // the finger afterward doesn't leak into
                                // anything else.
                                while (true) {
                                    val event = awaitPointerEvent()
                                    val change =
                                        event.changes.firstOrNull { it.id == down.id } ?: break
                                    change.consume()
                                    if (!change.pressed) break
                                }
                            }
                            resolved = true
                        } else {
                            // A clean, quick tap. Give it a moment to see if
                            // another one follows before deciding what this
                            // cluster means.
                            val nextDown = withTimeoutOrNull(viewConfiguration.doubleTapTimeoutMillis) {
                                awaitFirstDown()
                            }
                            if (nextDown == null || tapCount >= 3) {
                                when (tapCount) {
                                    1 -> onSelect(hitNode?.id)
                                    2 -> hitNode?.let {
                                        if (it.children.isNotEmpty()) onToggle(it.id)
                                    }
                                    else -> hitNode?.let { onOpenActions(it) }
                                }
                                resolved = true
                            } else {
                                down = nextDown
                            }
                        }
                    }
                }
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
                        // A single tap just selects — display-only, no
                        // model change — so it gets its own distinct ring
                        // color from the drop-target green.
                        if (v.node.id == selectedNodeId && !isDropTarget) {
                            drawRoundRect(
                                color = Color(0xFF1E88E5),
                                topLeft = drawRect.topLeft,
                                size = drawRect.size,
                                cornerRadius = androidx.compose.ui.geometry.CornerRadius(12f, 12f),
                                style = androidx.compose.ui.graphics.drawscope.Stroke(width = 3f / scale),
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
                        // Status badges — a row of small circles centered
                        // below the box (Windows's node_item.py has a
                        // "below" badge layout mode alongside its default
                        // beside-the-box one; that's the one that doesn't
                        // need the box itself measured wider to fit them).
                        // Same colors/glyphs as Windows: ToDo blue/red "D",
                        // priority 1-5 color-graded number, topic amber "T".
                        val badges = buildList {
                            if (v.node.todoMarked) {
                                val overdue = v.node.todoDueAt?.let {
                                    runCatching { LocalDate.parse(it) < LocalDate.now() }.getOrDefault(false)
                                } ?: false
                                add(
                                    Triple(
                                        if (overdue) Color(0xFFEF4444) else Color(0xFF3B82F6),
                                        if (overdue) Color(0xFF7F1D1D) else Color(0xFF1E3A8A),
                                        "D" to Color.White,
                                    )
                                )
                            }
                            v.node.priorityLevel?.let { level ->
                                val col = when (level) {
                                    1 -> Color(0xFFEF4444)
                                    2 -> Color(0xFFF97316)
                                    3 -> Color(0xFFEAB308)
                                    4 -> Color(0xFF84CC16)
                                    5 -> Color(0xFF3B82F6)
                                    else -> Color(0xFF9CA3AF)
                                }
                                add(Triple(col, Color(0xFF1F2937), level.toString() to Color.White))
                            }
                            if (v.node.isTopic) {
                                add(Triple(Color(0xFFF59E0B), Color(0xFF7C2D12), "T" to Color(0xFF1F2937)))
                            }
                        }
                        if (badges.isNotEmpty()) {
                            val badgeRadius = 11f
                            val badgeGap = 6f
                            val totalWidth = badges.size * (badgeRadius * 2) + (badges.size - 1) * badgeGap
                            var bx = drawRect.left + drawRect.width / 2f - totalWidth / 2f + badgeRadius
                            val by = drawRect.bottom + badgeGap + badgeRadius
                            for ((fillColor, strokeColor, labelAndColor) in badges) {
                                val (label, labelColor) = labelAndColor
                                val center = Offset(bx, by)
                                drawCircle(color = fillColor, radius = badgeRadius, center = center)
                                drawCircle(
                                    color = strokeColor,
                                    radius = badgeRadius,
                                    center = center,
                                    style = androidx.compose.ui.graphics.drawscope.Stroke(width = 1.5f),
                                )
                                val badgeStyle = TextStyle(
                                    fontSize = 11.sp,
                                    color = labelColor,
                                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                )
                                val measured = textMeasurer.measure(label, badgeStyle)
                                drawText(
                                    textMeasurer = textMeasurer,
                                    text = label,
                                    topLeft = Offset(
                                        bx - measured.size.width / 2f,
                                        by - measured.size.height / 2f,
                                    ),
                                    style = badgeStyle,
                                )
                                bx += badgeRadius * 2 + badgeGap
                            }
                        }
                    }
                }
            }
        }

    }
}
