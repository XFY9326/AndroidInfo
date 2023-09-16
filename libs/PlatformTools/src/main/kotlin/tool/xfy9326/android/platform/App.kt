package tool.xfy9326.android.platform

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.core.NoOpCliktCommand
import com.github.ajalt.clikt.core.context
import com.github.ajalt.clikt.core.subcommands
import com.github.ajalt.clikt.output.MordantHelpFormatter
import com.github.ajalt.clikt.parameters.arguments.argument
import com.github.ajalt.clikt.parameters.arguments.convert
import com.github.ajalt.clikt.parameters.arguments.multiple
import com.github.ajalt.clikt.parameters.options.default
import com.github.ajalt.clikt.parameters.options.option
import com.github.ajalt.clikt.parameters.options.required
import com.github.ajalt.clikt.parameters.types.file
import com.github.ajalt.clikt.parameters.types.path
import kotlinx.coroutines.*
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import tool.xfy9326.android.platform.analyzer.AuthorityClassesAnalyzer
import tool.xfy9326.android.platform.analyzer.FieldTypeAnalyzer
import java.io.File
import java.nio.file.Path
import kotlin.io.path.absolutePathString
import kotlin.io.path.createDirectories
import kotlin.io.path.notExists
import kotlin.io.path.writeText

fun main(args: Array<String>) {
    JarCommand().subcommands(AuthorityClassesCommand(), FieldTypeCommand()).main(args)
}

private class JarCommand : NoOpCliktCommand(name = "java -jar <FILE>.jar") {
    init {
        context {
            helpFormatter = { MordantHelpFormatter(it, showDefaultValues = true) }
        }
    }
}

private class AuthorityClassesCommand : CliktCommand(
    name = "authority-classes", help = "Dump android authority classes"
) {
    private val output: Path by option(
        names = arrayOf("-o", "--output"), help = "Result output dir"
    ).path(mustExist = false, canBeFile = false).default(Path.of("."))
    private val platforms: List<File> by argument(
        help = "Android platform zip files"
    ).file(mustExist = true, canBeDir = false).multiple(required = true)

    private val json = Json {
        prettyPrint = true
        encodeDefaults = true
        ignoreUnknownKeys = true
    }

    override fun run(): Unit = runBlocking {
        suspendRun()
    }

    private suspend fun suspendRun() = coroutineScope {
        if (output.notExists()) output.createDirectories()
        platforms.map {
            async(Dispatchers.IO) {
                val authoritiesMap = AuthorityClassesAnalyzer.getAuthorities(it)
                val dumpResult = authoritiesMap.map { it.key to it.value.frozen() }.toMap()
                val dumpPath = output.resolve(it.nameWithoutExtension + ".json")

                dumpPath.writeText(json.encodeToString(dumpResult))

                it.toPath().toRealPath().normalize() to dumpPath.toRealPath().normalize()
            }
        }.awaitAll().forEach {
            println("${it.first.absolutePathString()} -> ${it.second.absolutePathString()}")
        }
    }
}

private class FieldTypeCommand : CliktCommand(
    name = "field-type", help = "Dump android sdk field types"
) {
    private val platform: File by option(
        names = arrayOf("-p", "--platform"), help = "Android platform zip file"
    ).file(mustExist = true, canBeDir = false).required()
    private val source: File by option(
        names = arrayOf("-s", "--source"), help = "Android source zip file"
    ).file(mustExist = true, canBeDir = false).required()
    private val fields: List<ClassField> by argument(
        help = "Class and field (ClassName:FieldName)"
    ).convert { ClassField.parse(it) }.multiple(required = true)

    override fun run(): Unit = runBlocking {
        suspendRun()
    }

    private suspend fun suspendRun() = coroutineScope {
        FieldTypeAnalyzer.getFieldTypes(
            platformZip = platform, sourceZip = source, fields = fields
        ).forEach { (classField, typeName) ->
            println("${classField.output()} -> $typeName")
        }
    }
}
