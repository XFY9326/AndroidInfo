package tool.xfy9326.android.platform.analyzer

import javassist.bytecode.AccessFlag
import javassist.bytecode.ClassFile
import tool.xfy9326.android.platform.Authority
import tool.xfy9326.android.platform.className
import tool.xfy9326.android.platform.entryAsSequence
import tool.xfy9326.android.platform.openAndroidJarInputStream
import java.io.DataInputStream
import java.io.File
import java.util.jar.JarInputStream
import java.util.zip.ZipFile


object AuthorityClassesAnalyzer {
    private const val FIELD_AUTHORITY = "AUTHORITY"
    private const val PROVIDER_PACKAGE = "android/provider/"

    private fun JarInputStream.getProviderClassFiles(): List<ClassFile> = entryAsSequence().filter {
        !it.isDirectory && it.realName.startsWith(PROVIDER_PACKAGE)
    }.map {
        ClassFile(DataInputStream(this))
    }.toList()

    private fun ClassFile.getFieldAuthorityString(): String? = fields.firstOrNull {
        it != null && AccessFlag.isPublic(accessFlags) && it.name == FIELD_AUTHORITY
    }?.let {
        constPool.getStringInfo(it.constantValue)
    }

    fun getAuthorities(platformZipFile: File): Map<String, Authority> = ZipFile(platformZipFile).use { zipFile ->
        val androidJarStream = zipFile.openAndroidJarInputStream()
        val providerClassFiles = androidJarStream.getProviderClassFiles()
        val classAuthorityMap = providerClassFiles.asSequence().mapNotNull { classFile ->
            val authority = classFile.getFieldAuthorityString() ?: return@mapNotNull null
            classFile.className to authority
        }.toMap()
        val providerClassNames = providerClassFiles.mapNotNull { e ->
            e.className.takeIf { it !in classAuthorityMap }
        }
        buildMap {
            for ((className, authority) in classAuthorityMap) {
                this[authority]?.classNames?.add(className) ?: put(
                    authority, Authority(authority, mutableSetOf(className), mutableSetOf())
                )
            }
            for (authorityClass in values) {
                for (name in providerClassNames) {
                    if (authorityClass.classNames.any { name in it } && name !in classAuthorityMap) {
                        authorityClass.relatedClassNames.add(name)
                    }
                }
            }
        }
    }
}