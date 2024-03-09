package tool.xfy9326.android.platform.analyzer

import com.github.javaparser.StaticJavaParser
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration
import com.github.javaparser.symbolsolver.JavaSymbolSolver
import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver
import com.github.javaparser.symbolsolver.resolution.typesolvers.TypeSolverBuilder
import javassist.bytecode.ClassFile
import javassist.bytecode.SignatureAttribute
import tool.xfy9326.android.platform.*
import java.io.DataInputStream
import java.io.File
import java.io.InputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import kotlin.jvm.optionals.getOrNull


object FieldTypeAnalyzer {
    private const val SRC_DIR = "src"
    private const val ENTRY_DIV = "/"

    private fun ZipFile.getSrcEntry(field: ClassField): ZipEntry? = getEntry(SRC_DIR + ENTRY_DIV + field.className.javaSourceFilePath)

    private fun List<ClassField>.buildClassIndex() = buildMap<String, MutableList<ClassField>> {
        for (field in this@buildClassIndex) {
            this[field.className.javaJarEntryPath]?.add(field) ?: put(field.className.javaJarEntryPath, mutableListOf(field))
        }
    }

    private fun List<ClassField>.buildNameIndex() = buildMap {
        if (this@buildNameIndex.isEmpty()) {
            return@buildMap
        } else if (this@buildNameIndex.size == 1) {
            this@buildNameIndex.first().let {
                this[it.fieldName] = it
            }
        } else {
            val targetClassName = this@buildNameIndex.first().className
            for (field in this@buildNameIndex) {
                require(targetClassName == field.className) {
                    "Require all fields in one class $targetClassName. Current: ${field.className}"
                }
                this[field.fieldName] = field
            }
        }
    }

    fun getFieldTypes(platformZip: File, sourceZip: File, fields: List<ClassField>): Map<ClassField, String> =
        ZipFile(sourceZip).use { sourceFile ->
            ZipFile(platformZip).use { platformFile ->
                StaticJavaParser.getParserConfiguration().setSymbolResolver(
                    JavaSymbolSolver(
                        TypeSolverBuilder().with(JarTypeSolver(platformFile.openAndroidInputStream())).build()
                    )
                )
                buildMap {
                    val missingFields = mutableListOf<ClassField>()
                    putAll(getFieldTypeInSource(sourceFile, fields) { missingFields.add(it) })

                    if (missingFields.isNotEmpty()) {
                        putAll(getFieldTypeInAndroidJar(platformFile, missingFields))
                    }
                }.also {
                    for (field in fields) {
                        require(field in it) { "Can't find field ${field.fieldName} in class ${field.className}" }
                    }
                }
            }
        }

    private fun getFieldTypeInSource(
        sourceFile: ZipFile,
        fields: List<ClassField>,
        onFieldNotFound: (ClassField) -> Unit
    ): Sequence<Pair<ClassField, String>> {
        return getFieldTypeInStream(
            fields = fields,
            onLoadSource = {
                val entry = sourceFile.getSrcEntry(it)
                if (entry != null) {
                    sourceFile.getInputStream(entry)
                } else {
                    onFieldNotFound(it)
                    null
                }
            },
            onFieldNotFound = onFieldNotFound
        )
    }

    private fun getFieldTypeInStream(
        fields: List<ClassField>,
        onLoadSource: (ClassField) -> InputStream?,
        onFieldNotFound: (ClassField) -> Unit
    ): Sequence<Pair<ClassField, String>> {
        val classCache = mutableMapOf<String, ClassOrInterfaceDeclaration>()

        return fields.asSequence().mapNotNull {
            val classSimpleName = it.className.simpleName
            val classDeclaration = if (classSimpleName in classCache) {
                classCache[classSimpleName]
            } else {
                onLoadSource(it)?.let { stream ->
                    StaticJavaParser.parse(stream).getClassByClassName(classSimpleName).also { clazz ->
                        if (clazz != null) classCache[classSimpleName] = clazz
                    }
                }
            }
            val fieldType = classDeclaration?.getFieldByName(it.fieldName)?.getOrNull()?.elementType
            if (fieldType == null) {
                onFieldNotFound(it)
                null
            } else {
                it to fieldType.resolve().describe()
            }
        }
    }

    private fun getFieldTypeInAndroidJar(
        platformFile: ZipFile,
        fields: List<ClassField>
    ): Sequence<Pair<ClassField, String>> {
        val androidJarStream = platformFile.openAndroidJarInputStream()
        val classFieldIndex = fields.buildClassIndex()
        return androidJarStream.entryAsSequence().filterNot {
            it.isDirectory
        }.mapNotNull {
            classFieldIndex[it.realName]?.let { f ->
                ClassFile(DataInputStream(androidJarStream)) to f.buildNameIndex()
            }
        }.flatMap { (classFile, classFields) ->
            classFile.fields.asSequence().filterNotNull().mapNotNull {
                classFields[it.name]?.let { f ->
                    f to SignatureAttribute.toFieldSignature(it.descriptor).jvmTypeName()
                }
            }
        }
    }
}