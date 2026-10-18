plugins {
    id("com.android.application")
}

android {
    namespace = "com.biokpl.gridwatch.watchface"
    compileSdk = 35
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "com.biokpl.gridwatch.watchface"
        minSdk = 33
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }
    buildTypes {
        getByName("release") { isMinifyEnabled = false }
    }
}
