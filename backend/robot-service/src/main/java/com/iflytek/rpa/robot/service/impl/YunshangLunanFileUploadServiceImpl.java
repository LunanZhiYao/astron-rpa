package com.iflytek.rpa.robot.service.impl;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.iflytek.rpa.robot.entity.vo.YunshangLunanUploadResultVo;
import com.iflytek.rpa.robot.service.YunshangLunanFileUploadService;
import com.iflytek.rpa.robot.util.YunshangLunanCrypto;
import com.iflytek.rpa.utils.exception.ServiceException;
import com.iflytek.rpa.utils.response.ErrorCodeEnum;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

@Slf4j
@Service
public class YunshangLunanFileUploadServiceImpl implements YunshangLunanFileUploadService {

    @Value("${yunshang.lunan.upload-url:}")
    private String uploadUrl;

    @Value("${yunshang.lunan.upload-code:}")
    private String uploadCode;

    @Value("${yunshang.lunan.aes-key:}")
    private String aesKey;

    @Value("${yunshang.lunan.aes-iv:}")
    private String aesIv;

    @Override
    public YunshangLunanUploadResultVo upload(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new ServiceException(ErrorCodeEnum.E_PARAM.getCode(), "上传文件不能为空");
        }
        String url = StringUtils.trimToEmpty(uploadUrl);
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            throw new ServiceException(
                    ErrorCodeEnum.E_SERVICE.getCode(),
                    "未配置有效上传地址 yunshang.lunan.upload-url（YUNSHANG_LUNAN_UPLOAD_URL）");
        }
        if (StringUtils.isBlank(uploadCode)) {
            throw new ServiceException(
                    ErrorCodeEnum.E_SERVICE.getCode(), "未配置上传 code（YUNSHANG_LUNAN_UPLOAD_CODE）");
        }
        if (StringUtils.isBlank(aesKey) || StringUtils.isBlank(aesIv)) {
            throw new ServiceException(
                    ErrorCodeEnum.E_SERVICE.getCode(),
                    "未配置 AES 参数（YUNSHANG_LUNAN_AES_KEY / YUNSHANG_LUNAN_AES_IV）");
        }

        try {
            byte[] fileBytes = file.getBytes();
            String originalFileName = StringUtils.defaultIfBlank(file.getOriginalFilename(), "upload.bin");

            HttpHeaders fileHeaders = new HttpHeaders();
            fileHeaders.setContentType(MediaType.APPLICATION_OCTET_STREAM);
            ByteArrayResource fileResource = new ByteArrayResource(fileBytes) {
                @Override
                public String getFilename() {
                    return originalFileName;
                }
            };

            MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
            body.add("file", new HttpEntity<>(fileResource, fileHeaders));
            body.add("code", uploadCode);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.MULTIPART_FORM_DATA);
            HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

            ResponseEntity<String> response = buildRestTemplate().postForEntity(url, requestEntity, String.class);
            if (!response.getStatusCode().is2xxSuccessful()) {
                throw new ServiceException(
                        ErrorCodeEnum.E_SERVICE.getCode(),
                        "云上鲁南上传接口 HTTP 失败: " + response.getStatusCodeValue());
            }
            String bodyText = StringUtils.defaultString(response.getBody());
            JSONObject responseJson = JSON.parseObject(bodyText);
            if (responseJson == null) {
                throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "云上鲁南上传返回 JSON 解析失败");
            }
            if (responseJson.getIntValue("status") != 200) {
                throw new ServiceException(
                        ErrorCodeEnum.E_SERVICE.getCode(),
                        "云上鲁南上传业务失败 status=" + responseJson.getString("status"));
            }
            String encryptedCode = responseJson.getString("code");
            if (StringUtils.isBlank(encryptedCode)) {
                throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "云上鲁南上传返回缺少 code 字段");
            }
            String decrypted = YunshangLunanCrypto.aesCbcPkcs5DecryptBase64(encryptedCode, aesKey, aesIv);
            JSONObject payload = JSON.parseObject(decrypted);
            if (payload == null) {
                throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "云上鲁南上传 code 解密后非 JSON");
            }
            String link = payload.getString("link");
            if (StringUtils.isBlank(link)) {
                throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "云上鲁南上传结果缺少 link");
            }

            YunshangLunanUploadResultVo result = new YunshangLunanUploadResultVo();
            result.setFileUrl(link);
            result.setFileName(originalFileName);
            result.setFileSize(file.getSize());
            return result;
        } catch (ServiceException e) {
            throw e;
        } catch (Exception e) {
            log.error("云上鲁南文件上传失败", e);
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "云上鲁南文件上传失败: " + e.getMessage());
        }
    }

    private static RestTemplate buildRestTemplate() {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(30000);
        requestFactory.setReadTimeout(120000);
        return new RestTemplate(requestFactory);
    }
}
