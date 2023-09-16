package tool.xfy9326.android.platform

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder

data class Authority(
    val authority: String,
    val classNames: MutableSet<ClassName>,
    val relatedClassNames: MutableSet<ClassName>
) {
    fun frozen() = AuthorityClassName(
        authority = authority,
        classNames = classNames.toList().sortedBy { it.value },
        relatedClassNames = relatedClassNames.toList().sortedBy { it.value }
    )
}

@Serializable
data class AuthorityClassName(
    val authority: String,
    @SerialName("names")
    val classNames: List<ClassName>,
    @SerialName("related_names")
    val relatedClassNames: List<ClassName>
)

data class ClassField(
    val className: ClassName,
    val fieldName: String
) {
    companion object {
        private const val DIVIDER = ":"
        private const val VALID_FIELD_PATTERN = "^[a-zA-Z_$][a-zA-Z0-9_$]*$"

        fun parse(text: String): ClassField =
            text.split(DIVIDER).let {
                ClassField(ClassName(it[0]), it[1])
            }
    }

    init {
        require(VALID_FIELD_PATTERN.toRegex().matches(fieldName)) {
            "Not a valid field name: $fieldName"
        }
    }

    fun output() = "$className$DIVIDER$fieldName"
}

@Suppress("MemberVisibilityCanBePrivate")
@Serializable(ClassName.Serializer::class)
data class ClassName(val value: String) {
    companion object {
        private const val INNER_CLASS_SYMBOL = "$"
        private const val VALID_CLASS_NAME_PATTERN = "^[a-zA-Z_\$][a-zA-Z\\d_\$]*(?:\\.[a-zA-Z_\$][a-zA-Z\\d_\$]*)*\$"
    }

    init {
        require(VALID_CLASS_NAME_PATTERN.toRegex().matches(value)) {
            "Not a valid class name: $value"
        }
    }

    val fullName: String by lazy {
        value.substringAfterLast(".")
    }

    val simpleName: String by lazy {
        if ("." in fullName) {
            fullName.substringAfterLast(".")
        } else {
            fullName
        }
    }

    val javaSourceFilePath: String by lazy {
        value.substringBefore("$").replace(".", "/") + ".java"
    }

    val javaJarEntryPath: String by lazy {
        value.replace(".", "/") + ".class"
    }

    val isInnerClass: Boolean by lazy {
        INNER_CLASS_SYMBOL in value
    }

    operator fun contains(className: ClassName): Boolean =
        className.isInnerClass && className.fullName.startsWith(fullName + INNER_CLASS_SYMBOL)


    override fun toString(): String {
        return value
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false

        other as ClassName

        return value == other.value
    }

    override fun hashCode(): Int {
        return value.hashCode()
    }

    class Serializer : KSerializer<ClassName> {
        override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor(javaClass.simpleName, PrimitiveKind.STRING)

        override fun deserialize(decoder: Decoder) = ClassName(decoder.decodeString())

        override fun serialize(encoder: Encoder, value: ClassName) = encoder.encodeString(value.value)
    }
}