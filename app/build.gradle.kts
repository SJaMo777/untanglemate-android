plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

android {
    namespace = "com.syntheticcodelab.untanglemate"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.syntheticcodelab.untanglemate"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "0.0.1"

        // Chaquopy needs to know which device ABIs to bundle a Python
        // interpreter for. arm64-v8a covers essentially every real
        // phone/tablet sold in the last several years; x86_64 is for the
        // emulator on a normal PC.
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

// The Python side of the bridge: synmind/core/ is copied into
// app/src/main/python (see README-ANDROID.md for how/why), and imported
// from Kotlin via Chaquopy's Python.getInstance().
chaquopy {
    defaultConfig {
        version = "3.12"
        // Chaquopy runs pip locally (on THIS machine, not the phone) to
        // resolve packages before bundling them for Android, and by
        // default looks for a build-machine Python matching the target
        // version above. Only 3.12 is installed here, so point it there
        // explicitly — it only needs to run pip, it doesn't need to
        // match 3.11 itself.
        buildPython("C:\\Users\\sjmin\\AppData\\Local\\Programs\\Python\\Python312\\python.exe")
        pip {
            // Matches synmind/core/file_format.py's Fernet-encrypted
            // .smmap format exactly — this MUST stay compatible with
            // whatever `cryptography` does on the Windows side, since
            // both platforms read/write the same files.
            install("cryptography")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.material3:material3")
}
