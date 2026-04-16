package com.iflytek.rpa.robot.util;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** AES/CBC/PKCS5Padding，Base64 输出（云上鲁南消息体字段加密）。 */
public final class YunshangLunanCrypto {

    private static final String AES = "AES";
    private static final String AES_CBC_PKCS5 = "AES/CBC/PKCS5Padding";

    private YunshangLunanCrypto() {}

    public static String aesCbcPkcs5EncryptBase64(String plain, String keyUtf8, String ivUtf8) throws Exception {
        if (plain == null) {
            return "";
        }
        byte[] keyBytes = normalizeKey(keyUtf8);
        byte[] ivBytes = normalizeIv(ivUtf8);
        SecretKeySpec keySpec = new SecretKeySpec(keyBytes, AES);
        IvParameterSpec ivSpec = new IvParameterSpec(ivBytes);
        Cipher cipher = Cipher.getInstance(AES_CBC_PKCS5);
        cipher.init(Cipher.ENCRYPT_MODE, keySpec, ivSpec);
        byte[] encrypted = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(encrypted);
    }

    public static String aesCbcPkcs5DecryptBase64(String encryptedBase64, String keyUtf8, String ivUtf8)
            throws Exception {
        if (encryptedBase64 == null) {
            return "";
        }
        byte[] keyBytes = normalizeKey(keyUtf8);
        byte[] ivBytes = normalizeIv(ivUtf8);
        SecretKeySpec keySpec = new SecretKeySpec(keyBytes, AES);
        IvParameterSpec ivSpec = new IvParameterSpec(ivBytes);
        Cipher cipher = Cipher.getInstance(AES_CBC_PKCS5);
        cipher.init(Cipher.DECRYPT_MODE, keySpec, ivSpec);
        byte[] decoded = Base64.getDecoder().decode(encryptedBase64);
        byte[] decrypted = cipher.doFinal(decoded);
        return new String(decrypted, StandardCharsets.UTF_8);
    }

    /**
     * 兼容 PHP:
     * <pre>
     * $user_id = urlsafe_b64decode($code);
     * openssl_decrypt($user_id, 'AES-128-CBC', $key, 0, $iv);
     * </pre>
     */
    public static String aesCbcPkcs5DecryptPhpCompatible(String encryptedCode, String keyUtf8, String ivUtf8)
            throws Exception {
        if (encryptedCode == null) {
            return "";
        }
        Exception last = null;
        for (String candidate : buildDecryptCandidates(encryptedCode)) {
            try {
                return aesCbcPkcs5DecryptBase64(candidate, keyUtf8, ivUtf8);
            } catch (Exception ex) {
                last = ex;
            }
        }
        if (last != null) {
            throw last;
        }
        throw new IllegalArgumentException("empty encrypted code");
    }

    private static String[] buildDecryptCandidates(String encryptedCode) {
        String src = encryptedCode.trim();
        String normalizedUrlSafe = normalizeUrlSafeBase64(src);
        String decodedAsText = tryDecodeUrlSafeToText(src);
        String decodedAsTextNormalized =
                decodedAsText == null ? null : normalizeStandardBase64(decodedAsText.trim());
        return new String[] {
            src,
            normalizeStandardBase64(src),
            normalizedUrlSafe,
            decodedAsText,
            decodedAsTextNormalized
        };
    }

    private static String tryDecodeUrlSafeToText(String input) {
        try {
            byte[] decoded = Base64.getUrlDecoder().decode(padBase64(input));
            return new String(decoded, StandardCharsets.UTF_8);
        } catch (Exception ignore) {
            return null;
        }
    }

    private static String normalizeUrlSafeBase64(String input) {
        String normalized = input.replace('-', '+').replace('_', '/');
        return padBase64(normalized);
    }

    private static String normalizeStandardBase64(String input) {
        return padBase64(input.replaceAll("\\s+", ""));
    }

    private static String padBase64(String input) {
        if (input == null) {
            return null;
        }
        String noSpace = input.replaceAll("\\s+", "");
        int mod = noSpace.length() % 4;
        if (mod == 0) {
            return noSpace;
        }
        StringBuilder sb = new StringBuilder(noSpace);
        for (int i = 0; i < 4 - mod; i++) {
            sb.append('=');
        }
        return sb.toString();
    }

    private static byte[] normalizeKey(String keyUtf8) {
        byte[] raw = keyUtf8.getBytes(StandardCharsets.UTF_8);
        int len = raw.length;
        if (len == 16 || len == 24 || len == 32) {
            return raw;
        }
        if (len < 16) {
            return Arrays.copyOf(raw, 16);
        }
        if (len < 24) {
            return Arrays.copyOf(raw, 24);
        }
        if (len < 32) {
            return Arrays.copyOf(raw, 32);
        }
        return Arrays.copyOf(raw, 32);
    }

    private static byte[] normalizeIv(String ivUtf8) {
        byte[] raw = ivUtf8.getBytes(StandardCharsets.UTF_8);
        return Arrays.copyOf(raw, 16);
    }
}
