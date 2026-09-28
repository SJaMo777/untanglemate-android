package com.syntheticcodelab.untanglemate

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Chaquopy's interpreter is process-wide and only needs starting
        // once; every Activity/Fragment created later just calls
        // Python.getInstance().
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        // Proof of the whole point of this project: synmind/core/model.py
        // is the EXACT SAME FILE the Windows app runs, copied in
        // unmodified under app/src/main/python. If this reads back a
        // real MindMap/Node built by that file, the Chaquopy bridge
        // works end to end, not just "it compiled".
        val python = Python.getInstance()
        val model = python.getModule("synmind.core.model")
        val mindMap = model.callAttr("MindMap")
        val rootNodeText = mindMap.get("root")!!.get("text").toString()
        val coreVersion = python.getModule("synmind").get("__version__").toString()

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    Column(
                        modifier = Modifier.fillMaxSize().padding(24.dp),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text("UnTangleMate (Android)", style = MaterialTheme.typography.headlineSmall)
                        Text("synmind.core version $coreVersion")
                        Text("Chaquopy bridge OK — root node reads back as \"$rootNodeText\"")
                    }
                }
            }
        }
    }
}
