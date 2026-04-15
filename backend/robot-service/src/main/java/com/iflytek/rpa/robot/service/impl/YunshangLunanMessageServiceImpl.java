package com.iflytek.rpa.robot.service.impl;

import com.iflytek.rpa.robot.entity.dto.YunshangLunanSendDto;
import com.iflytek.rpa.robot.service.YunshangLunanMessageService;
import com.iflytek.rpa.robot.util.YunshangLunanCrypto;
import com.iflytek.rpa.robot.util.YunshangLunanSignUtil;
import com.iflytek.rpa.utils.exception.ServiceException;
import com.iflytek.rpa.utils.response.ErrorCodeEnum;
import java.util.HashMap;
import java.util.Map;
import java.util.TreeMap;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Slf4j
@Service
public class YunshangLunanMessageServiceImpl implements YunshangLunanMessageService {

    private static final String METHOD = "app.message.send.advance";
    private static final String APP_ID = "one_team";
    private static final String SEND_TYPE = "U2U";

    @Value("${yunshang.lunan.url:}")
    private String apiUrl;

    @Value("${yunshang.lunan.app-secret:}")
    private String appSecret;

    @Value("${yunshang.lunan.token:}")
    private String token;

    @Value("${yunshang.lunan.sender-id:}")
    private String senderId;

    @Value("${yunshang.lunan.aes-key:}")
    private String aesKey;

    @Value("${yunshang.lunan.aes-iv:}")
    private String aesIv;

    @Override
    public String send(YunshangLunanSendDto dto) {
        if (dto == null) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "请求体为空");
        }
        String outboundUrl = StringUtils.trimToEmpty(apiUrl);
        if (StringUtils.isBlank(outboundUrl)) {
            throw new ServiceException(
                    ErrorCodeEnum.E_SERVICE.getCode(),
                    "未配置云上鲁南接口地址：请在运行 robot-service 的环境中设置 YUNSHANG_LUNAN_API_URL（完整 https:// 或 http:// URL），"
                            + "并确认已重新编译/部署含 application.yml 的服务或已重启容器");
        }
        if (!outboundUrl.startsWith("http://") && !outboundUrl.startsWith("https://")) {
            throw new ServiceException(
                    ErrorCodeEnum.E_SERVICE.getCode(),
                    "yunshang.lunan.url 必须为以 http:// 或 https:// 开头的完整地址，当前配置无效");
        }
        if (StringUtils.isBlank(appSecret)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "未配置 yunshang.lunan.app-secret（YUNSHANG_LUNAN_APP_SECRET）");
        }
        if (StringUtils.isBlank(token)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "未配置 yunshang.lunan.token（YUNSHANG_LUNAN_TOKEN）");
        }
        if (StringUtils.isBlank(senderId)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "未配置 yunshang.lunan.sender-id（YUNSHANG_LUNAN_SENDER_ID）");
        }
        if (StringUtils.isBlank(aesKey) || StringUtils.isBlank(aesIv)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "未配置 yunshang.lunan.aes-key / aes-iv（YUNSHANG_LUNAN_AES_KEY、YUNSHANG_LUNAN_AES_IV）");
        }
        String receiverId = StringUtils.trimToEmpty(dto.getReceiverId());
        if (StringUtils.isBlank(receiverId)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "receiver_id 不能为空");
        }
        String msgType = StringUtils.trimToEmpty(dto.getMsgType());
        if (!"Text".equals(msgType) && !"File".equals(msgType)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "msg_type 必须为 Text 或 File");
        }
        String plainText = dto.getText() == null ? "" : dto.getText();
        String plainLink = dto.getLink() == null ? "" : dto.getLink();
        String fileName = dto.getFileName() == null ? "" : dto.getFileName();
        String fileSize = dto.getFileSize() == null ? "" : dto.getFileSize();
        if ("Text".equals(msgType) && StringUtils.isBlank(plainText)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "文本消息时 text 不能为空");
        }
        if ("File".equals(msgType) && StringUtils.isBlank(plainLink)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "文件消息时 link 不能为空");
        }
        if ("File".equals(msgType) && StringUtils.isBlank(fileName)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "文件消息时 file_name 不能为空");
        }
        if ("File".equals(msgType) && StringUtils.isBlank(fileSize)) {
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "文件消息时 file_size 不能为空");
        }
        if ("File".equals(msgType)) {
            plainText = buildFileMetaText(fileName, fileSize);
        }

        String encText;
        String encLink;
        try {
            encText = StringUtils.isBlank(plainText) ? "" : YunshangLunanCrypto.aesCbcPkcs5EncryptBase64(plainText, aesKey, aesIv);
            encLink = StringUtils.isBlank(plainLink) ? "" : YunshangLunanCrypto.aesCbcPkcs5EncryptBase64(plainLink, aesKey, aesIv);
        } catch (Exception e) {
            log.error("云上鲁南 AES 加密失败", e);
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "云上鲁南消息加密失败: " + e.getMessage());
        }

        String nonce = Long.toString(System.currentTimeMillis() / 1000L);
        String title = "";

        Map<String, String> forSign = new TreeMap<>();
        forSign.put("app_id", APP_ID);
        forSign.put("app_secret", appSecret);
        forSign.put("method", METHOD);
        forSign.put("msg_type", msgType);
        forSign.put("nonce", nonce);
        forSign.put("receiver_id", receiverId);
        forSign.put("send_type", SEND_TYPE);
        forSign.put("sender_id", senderId);
        forSign.put("text", encText);
        forSign.put("title", title);
        forSign.put("token", token);
        forSign.put("link", encLink);

        String sign = YunshangLunanSignUtil.erpSign(forSign, appSecret);

        Map<String, Object> body = new HashMap<>();
        body.put("app_id", APP_ID);
        body.put("method", METHOD);
        body.put("nonce", nonce);
        body.put("token", token);
        body.put("send_type", SEND_TYPE);
        body.put("msg_type", msgType);
        body.put("sender_id", senderId);
        body.put("receiver_id", receiverId);
        body.put("text", encText);
        body.put("title", title);
        body.put("link", encLink);
        body.put("sign", sign);

        RestTemplate restTemplate = buildRestTemplate();
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
        try {
            ResponseEntity<String> resp = restTemplate.postForEntity(outboundUrl, entity, String.class);
            if (!resp.getStatusCode().is2xxSuccessful()) {
                throw new ServiceException(
                        ErrorCodeEnum.E_SERVICE.getCode(),
                        "云上鲁南接口 HTTP 失败: " + resp.getStatusCodeValue());
            }
            return resp.getBody() != null ? resp.getBody() : "";
        } catch (ServiceException e) {
            throw e;
        } catch (Exception e) {
            log.error("云上鲁南接口请求失败", e);
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "云上鲁南接口请求失败: " + e.getMessage());
        }
    }

    private static RestTemplate buildRestTemplate() {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(30000);
        requestFactory.setReadTimeout(60000);
        return new RestTemplate(requestFactory);
    }

    private static String buildFileMetaText(String fileName, String fileSize) {
        return "{\"fileName\":\"" + jsonEscape(fileName) + "\",\"fileSize\":\"" + jsonEscape(fileSize) + "\"}";
    }

    private static String jsonEscape(String value) {
        String text = value == null ? "" : value;
        return text.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
