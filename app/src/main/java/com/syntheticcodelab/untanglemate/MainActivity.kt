package com.syntheticcodelab.untanglemate

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File

/** One node in the tree, as parsed from android_bridge's JSON. Mirrors
 * synmind.core.model.Node loosely — id/text/collapsed/children only,
 * nothing else is needed for this screen yet. */
data class MapNode(
    val id: String,
    val text: String,
    val children: List<MapNode>,
)

private fun parseNode(obj: JSONObject): MapNode {
    val childrenArray = obj.getJSONArray("children")
    val children = (0 until childrenArray.length()).map { i ->
        parseNode(childrenArray.getJSONObject(i))
    }
    return MapNode(obj.getString("id"), obj.getString("text"), children)
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
            var title by remember { mutableStateOf("Untitled") }
            var root by remember {
                mutableStateOf(parseNode(JSONObject(bridge.callAttr("new_map_as_json").toString()).getJSONObject("root")))
            }
            // expand/collapse is UI-only for now — does not touch the
            // model's own `collapsed` field (see README-ANDROID.md: not
            // done yet, no editing, this screen only reads).
            val expanded = remember { mutableStateOf(setOf(root.id)) }

            fun loadFromPath(path: String) {
                val json = JSONObject(bridge.callAttr("load_map_as_json", path).toString())
                title = json.getString("title")
                root = parseNode(json.getJSONObject("root"))
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
                    Scaffold(
                        topBar = {},
                    ) { padding ->
                        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
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
                            NodeTree(root, depth = 0, expanded = expanded.value) { id ->
                                expanded.value = if (id in expanded.value) {
                                    expanded.value - id
                                } else {
                                    expanded.value + id
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun NodeTree(
    node: MapNode,
    depth: Int,
    expanded: Set<String>,
    onToggle: (String) -> Unit,
) {
    LazyColumn {
        renderNode(node, depth, expanded, onToggle)
    }
}

// LazyListScope, not a @Composable — lets NodeTree stay a single
// LazyColumn for the whole tree instead of nesting one per level (which
// Compose doesn't allow: LazyColumn can't be nested inside LazyColumn).
private fun androidx.compose.foundation.lazy.LazyListScope.renderNode(
    node: MapNode,
    depth: Int,
    expanded: Set<String>,
    onToggle: (String) -> Unit,
) {
    item(key = node.id) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(enabled = node.children.isNotEmpty()) { onToggle(node.id) }
                .padding(start = (depth * 20).dp, top = 8.dp, bottom = 8.dp),
        ) {
            val marker = when {
                node.children.isEmpty() -> "  "
                node.id in expanded -> "▾ "
                else -> "▸ "
            }
            Text(marker + node.text)
        }
    }
    if (node.id in expanded) {
        node.children.forEach { child ->
            renderNode(child, depth + 1, expanded, onToggle)
        }
    }
}
