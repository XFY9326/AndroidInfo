import com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    application
    kotlin("jvm") version "2.0.20"
    kotlin("plugin.serialization") version "2.0.20"
    id("com.github.johnrengelman.shadow") version "8.1.1"
}

group = "tool.xfy9326.android.platform"
version = "1.2"

repositories {
    mavenCentral()
    google()
    maven {
        url = uri("https://jitpack.io")
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core-jvm:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.2")
    implementation("com.github.javaparser:javaparser-core:3.26.2")
    implementation("com.github.javaparser:javaparser-symbol-solver-core:3.26.2")
    implementation("com.github.ajalt.clikt:clikt-jvm:5.0.0")
    testImplementation(kotlin("test"))
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    jvmToolchain(17)
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
//        freeCompilerArgs.addAll(
//            "-opt-in=kotlinx.coroutines.ExperimentalCoroutinesApi",
//            "-opt-in=kotlinx.serialization.ExperimentalSerializationApi"
//        )
    }
}

application {
    mainClass.set("tool.xfy9326.android.platform.AppKt")
}

tasks.test {
    useJUnitPlatform()
}

tasks.jar { enabled = false }

artifacts.archives(tasks.shadowJar)

tasks.withType<ShadowJar> {
    // The jar remains up to date even when changing excludes
    // https://github.com/johnrengelman/shadow/issues/62
    outputs.upToDateWhen { false }

    exclude(
        "LICENSE",
        "arsclib.properties",
        "DebugProbesKt.bin",
        "META-INF/com.android.tools/**",
        "META-INF/maven/**",
        "META-INF/proguard/**",
        "META-INF/*.version",
        "META-INF/LICENSE",
        "META-INF/LICENSE.txt",
        "META-INF/LGPL2.1",
        "META-INF/AL2.0",
    )

    mergeServiceFiles()
}

tasks.register("releaseJar") {
    group = "release"
    dependsOn("clean")
    dependsOn(tasks.withType<ShadowJar>().map { it.name })
}
