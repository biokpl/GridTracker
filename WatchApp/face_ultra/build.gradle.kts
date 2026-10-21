plugins {
    id("com.android.application")
}

android {
    namespace = "com.biokpl.gridwatch.face.ultra"
    compileSdk = 35
    buildToolsVersion = "35.0.0"
    defaultConfig {
        applicationId = "com.biokpl.gridwatch.face.ultra"
        minSdk = 33
        targetSdk = 35
        versionCode = 29876730   // her üretimde yeni sürüm: saat çalışma zamanı önbelleğini tazeler
        versionName = "1.0"
    }
}
