package com.syntheticcodelab.untanglemate

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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
 * not a top-down tree. */
data class MapNode(
    val id: String,
    val text: String,
    val x: Float,
    val y: Float,
    val children: List<MapNode>,
)

private fun parseNode(obj: JSONObject): MapNode {
    val childrenArray = obj.getJSONArray("children")
    val children = (0 until childrenArray.length()).map { i ->
        parseNode(childrenArray.getJSONObject(i))
    }
    return MapNode(
        obj.getString("id"), obj.getString("text"),
        obj.getDouble("x").toFloat(), obj.getDouble("y").toFloat(),
        children,
    )
}

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
            // model's own `collapsed` field (see README-ANDROID.md: not
            // done yet, no editing, this screen only reads).
            val expanded = remember { mutableStateOf(setOf(root.id)) }

            fun loadFromPath(path: String) {
                val structureJson = bridge.callAttr("open_map_structure", path).toString()
                // Title doesn't need measuring — read it straight off the
                // structure call rather than round-tripping it through
                // apply_measured_layout too.
                title = JSONObject(structureJson).getString("title")
                root = applyStructureAndLayout(structureJson)
                expanded.value = setOf(root.id)
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
            }

            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    Column(modifier = Modifier.fillMaxSize()) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(title, style = MaterialTheme.typography.headlineSmall)
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                                horizontalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                Button(onClick = { openDocument.launch(arrayOf("*/*")) }) {
                                    Text("Open .smmap…")
                                }
                                if (BuildConfig.DEBUG) {
                                    // Dev-only: sidesteps the system file
                                    // picker's UI for adb-driven testing.
                                    // Never shown in a release build. Uses
                                    // the app's own external files dir, not
                                    // /sdcard/Download directly — scoped
                                    // storage blocks raw path access there
                                    // even for the app's own reads/writes,
                                    // which is exactly why the real Open
                                    // button above goes through SAF instead.
                                    Button(onClick = {
                                        val f = File(getExternalFilesDir(null), "test.smmap")
                                        loadFromPath(f.absolutePath)
                                    }) {
                                        Text("Load test map")
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
                        )
                    }
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
) {
    val textStyle = canvasTextStyle

    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }

    val visible = remember(root, expanded) {
        val out = mutableListOf<VisibleNode>()
        computeVisible(root, null, expanded, { text ->
            textMeasurer.measure(text, textStyle).size.let {
                androidx.compose.ui.geometry.Size(it.width.toFloat(), it.height.toFloat())
            }
        }, out)
        out
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                detectTransformGestures { _, pan, zoom, _ ->
                    scale = (scale * zoom).coerceIn(0.2f, 4f)
                    offset += pan
                }
            }
            .pointerInput(visible, scale, offset) {
                detectTapGestures { tapOffset ->
                    // Invert the same transform drawing applies below
                    // (translate to center + pan, then scale) to turn a
                    // screen tap back into a world-space point.
                    val centerX = size.width / 2f + offset.x
                    val centerY = size.height / 2f + offset.y
                    val worldX = (tapOffset.x - centerX) / scale
                    val worldY = (tapOffset.y - centerY) / scale
                    val hit = visible.lastOrNull { it.rect.contains(Offset(worldX, worldY)) }
                    if (hit != null && hit.node.children.isNotEmpty()) {
                        onToggle(hit.node.id)
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
                        val childCenter = v.rect.center
                        drawLine(
                            color = Color(0xFF9575CD),
                            start = parentCenter,
                            end = childCenter,
                            strokeWidth = 2f / scale,
                        )
                    }
                    for (v in visible) {
                        val isRoot = v.hasParent == null
                        drawRoundRect(
                            color = if (isRoot) Color(0xFF673AB7) else Color(0xFFEDE7F6),
                            topLeft = v.rect.topLeft,
                            size = v.rect.size,
                            cornerRadius = androidx.compose.ui.geometry.CornerRadius(12f, 12f),
                        )
                        drawText(
                            textMeasurer = textMeasurer,
                            text = v.node.text,
                            topLeft = Offset(
                                v.rect.left + NODE_PADDING_H,
                                v.rect.top + NODE_PADDING_V,
                            ),
                            style = textStyle.copy(
                                color = if (isRoot) Color.White else Color.Black,
                            ),
                        )
                    }
                }
            }
        }
    }
}
