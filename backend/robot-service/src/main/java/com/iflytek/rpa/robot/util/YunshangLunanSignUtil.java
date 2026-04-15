package com.iflytek.rpa.robot.util;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.TreeMap;
import org.springframework.util.DigestUtils;

/**
 * 与 {@code ErpApi::sign} 一致：ksort 后按 key 拼接 key+value，再 MD5(app_secret + exp + app_secret) 大写。
 */
public final class YunshangLunanSignUtil {

    private YunshangLunanSignUtil() {}

    public static String erpSign(Map<String, String> paramIncludingAppSecret, String appSecret) {
        TreeMap<String, String> sorted = new TreeMap<>(paramIncludingAppSecret);
        StringBuilder exp = new StringBuilder();
        for (Map.Entry<String, String> e : sorted.entrySet()) {
            String v = e.getValue() == null ? "" : e.getValue();
            exp.append(e.getKey()).append(v);
        }
        String raw = appSecret + exp + appSecret;
        return DigestUtils.md5DigestAsHex(raw.getBytes(StandardCharsets.UTF_8)).toUpperCase();
    }
}
