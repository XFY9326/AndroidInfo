package tool.xfy9326.android.platform

import com.github.javaparser.ast.Node
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration
import javassist.bytecode.ClassFile
import java.io.InputStream
import java.util.jar.JarEntry
import java.util.jar.JarInputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipFile

fun JarInputStream.entryAsSequence(): Sequence<JarEntry> = sequence {
    var entry: JarEntry?
    while (nextJarEntry.also { entry = it } != null) {
        try {
            yield(entry!!)
        } finally {
            closeEntry()
        }
    }
}

fun ZipFile.getAndroidJarEntry(): ZipEntry = "android-.*/android.jar".toRegex().let { regex ->
    entries().asSequence().filterNotNull().first {
        !it.isDirectory && regex.matches(it.name)
    }
}

fun ZipFile.openAndroidInputStream(): InputStream = getInputStream(getAndroidJarEntry())

fun ZipFile.openAndroidJarInputStream(): JarInputStream = JarInputStream(openAndroidInputStream())

val ClassFile.className: ClassName
    get() = ClassName(name.replace("/", "."))

fun Node.getClassByClassName(className: String): ClassOrInterfaceDeclaration? {
    val divIndex = className.indexOf("$")
    val levelName = if (divIndex < 0) {
        className
    } else {
        className.substring(0, divIndex)
    }
    val declaration = childNodes.asSequence()
        .filterNotNull()
        .filterIsInstance<ClassOrInterfaceDeclaration>()
        .filter { !it.isInterface }
        .firstOrNull { it.nameAsString == levelName }
    return if (divIndex < 0) {
        declaration
    } else {
        return declaration?.getClassByClassName(
            className.substring(divIndex + 1)
        )
    }
}
