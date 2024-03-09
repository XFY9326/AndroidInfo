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
            val classCache = mutableMapOf<String, ClassOrInterfaceDeclaration>()

            ZipFile(platformZip).use { platformFile ->
                StaticJavaParser.getParserConfiguration().setSymbolResolver(
                    JavaSymbolSolver(
                        TypeSolverBuilder().with(JarTypeSolver(platformFile.openAndroidInputStream())).build()
                    )
                )
                val notInSourceFields = mutableListOf<ClassField>()

                buildMap {
                    for (field in fields) {
                        val entry = sourceFile.getSrcEntry(field)
                        if (entry != null) {
                            val parser = StaticJavaParser.parse(sourceFile.getInputStream(entry))
                            val classSimpleName = field.className.simpleName
                            val classDeclaration = classCache[classSimpleName] ?: parser.getClassByClassName(classSimpleName)
                            val fieldType = classDeclaration?.getFieldByName(field.fieldName)?.getOrNull()?.elementType
                            if (fieldType == null) {
                                notInSourceFields.add(field)
                            } else {
                                put(field, fieldType.resolve().describe())
                            }
                        } else {
                            notInSourceFields.add(field)
                        }
                    }

                    if (notInSourceFields.isNotEmpty()) {
                        val androidJarStream = platformFile.openAndroidJarInputStream()
                        val classFieldIndex = notInSourceFields.buildClassIndex()
                        androidJarStream.entryAsSequence().filterNot {
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
                        }.forEach { (field, typeName) ->
                            put(field, typeName)
                        }

                        for (field in notInSourceFields) {
                            if (field !in this) {
                                error("Can't find field ${field.fieldName} in class ${field.className}")
                            }
                        }
                    }
                }
            }
        }
}