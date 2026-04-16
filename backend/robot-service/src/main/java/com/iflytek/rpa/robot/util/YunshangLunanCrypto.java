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
