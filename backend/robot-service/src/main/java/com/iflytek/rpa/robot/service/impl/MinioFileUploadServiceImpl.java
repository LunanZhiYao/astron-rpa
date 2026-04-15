package com.iflytek.rpa.robot.service.impl;

import com.iflytek.rpa.robot.entity.vo.MinioUploadResultVo;
import com.iflytek.rpa.robot.service.MinioFileUploadService;
import com.iflytek.rpa.utils.exception.ServiceException;
import com.iflytek.rpa.utils.response.ErrorCodeEnum;
import io.minio.BucketExistsArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.SetBucketPolicyArgs;
import java.io.InputStream;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.UUID;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

@Slf4j
@Service
public class MinioFileUploadServiceImpl implements MinioFileUploadService {
    private static final String DEFAULT_SCHEMA = "http";
    private static final String DEFAULT_ACCESS_POLICY = "public";

    @Value("${minio.endpoint:}")
    private String endpoint;

    @Value("${minio.access-key:}")
    private String accessKey;

    @Value("${minio.secret-key:}")
    private String secretKey;

    @Value("${minio.bucket:rpa-resource}")
    private String bucket;

    @Value("${minio.url-prefix:}")
    private String urlPrefix;

    @Override
    public MinioUploadResultVo upload(MultipartFile file, String objectName) {
        if (file == null || file.isEmpty()) {
            throw new ServiceException(ErrorCodeEnum.E_PARAM.getCode(), "上传文件不能为空");
        }
        if (StringUtils.isBlank(endpoint) || StringUtils.isBlank(accessKey) || StringUtils.isBlank(secretKey)) {
            throw new ServiceException(
                    ErrorCodeEnum.E_SERVICE.getCode(),
                    "未配置 MinIO 连接信息（LUNAN_MINIO_ENDPOINT/LUNAN_MINIO_ACCESS_KEY/LUNAN_MINIO_SECRET_KEY）");
        }

        String finalObjectName = buildObjectName(file.getOriginalFilename(), objectName);
        String normalizedEndpoint = normalizeEndpoint(endpoint);
        try {
            MinioClient client = MinioClient.builder()
                    .endpoint(normalizedEndpoint)
                    .credentials(accessKey, secretKey)
                    .build();
            ensureBucket(client, bucket);
            tryEnsureAccessPolicy(client, bucket);
            try (InputStream inputStream = file.getInputStream()) {
                client.putObject(PutObjectArgs.builder()
                        .bucket(bucket)
                        .object(finalObjectName)
                        .stream(inputStream, file.getSize(), -1)
                        .contentType(StringUtils.defaultIfBlank(file.getContentType(), "application/octet-stream"))
                        .build());
            }
        } catch (ServiceException e) {
            throw e;
        } catch (Exception e) {
            log.error("上传 MinIO 失败, object={}", finalObjectName, e);
            throw new ServiceException(ErrorCodeEnum.E_SERVICE.getCode(), "上传 MinIO 失败: " + e.getMessage());
        }

        MinioUploadResultVo result = new MinioUploadResultVo();
        result.setFileName(getFileNameFromObject(finalObjectName));
        result.setFileSize(file.getSize());
        result.setFileUrl(buildAccessUrl(finalObjectName));
        return result;
    }

    private static void ensureBucket(MinioClient client, String bucketName) throws Exception {
        boolean exists = client.bucketExists(BucketExistsArgs.builder().bucket(bucketName).build());
        if (!exists) {
            client.makeBucket(MakeBucketArgs.builder().bucket(bucketName).build());
        }
    }

    private static String buildObjectName(String originalFilename, String objectName) {
        if (StringUtils.isNotBlank(objectName)) {
            return objectName;
        }
        String fileName = StringUtils.defaultIfBlank(originalFilename, "upload.bin");
        String date = LocalDate.now().format(DateTimeFormatter.BASIC_ISO_DATE);
        return "internal/" + date + "/" + UUID.randomUUID().toString().replace("-", "") + "-" + fileName;
    }

    private String buildAccessUrl(String objectName) {
        if (StringUtils.isNotBlank(urlPrefix)) {
            return joinUrl(urlPrefix, bucket + "/" + objectName);
        }
        return joinUrl(normalizeEndpoint(endpoint), bucket + "/" + objectName);
    }

    private static String joinUrl(String base, String path) {
        String normalizedBase = StringUtils.removeEnd(base.trim(), "/");
        String normalizedPath = StringUtils.removeStart(path, "/");
        return normalizedBase + "/" + normalizedPath;
    }

    private static String getFileNameFromObject(String objectName) {
        int idx = objectName.lastIndexOf('/');
        if (idx < 0) {
            return objectName;
        }
        return objectName.substring(idx + 1);
    }

    private static String normalizeEndpoint(String rawEndpoint) {
        String endpointText = StringUtils.trimToEmpty(rawEndpoint);
        if (StringUtils.isBlank(endpointText)) {
            return endpointText;
        }
        if (endpointText.startsWith("http://") || endpointText.startsWith("https://")) {
            return endpointText;
        }
        return DEFAULT_SCHEMA + "://" + endpointText;
    }

    private static void ensureAccessPolicy(MinioClient client, String bucketName) throws Exception {
        if (!"public".equalsIgnoreCase(DEFAULT_ACCESS_POLICY)) {
            return;
        }
        String policy = "{"
                + "\"Version\":\"2012-10-17\","
                + "\"Statement\":[{"
                + "\"Effect\":\"Allow\","
                + "\"Principal\":{\"AWS\":[\"*\"]},"
                + "\"Action\":[\"s3:GetObject\"],"
                + "\"Resource\":[\"arn:aws:s3:::" + bucketName + "/*\"]"
                + "}]"
                + "}";
        client.setBucketPolicy(SetBucketPolicyArgs.builder().bucket(bucketName).config(policy).build());
    }

    private static void tryEnsureAccessPolicy(MinioClient client, String bucketName) {
        try {
            ensureAccessPolicy(client, bucketName);
        } catch (Exception e) {
            // 部分账号仅有上传权限，无 SetBucketPolicy 权限；不应阻断上传主流程
            log.warn("设置 MinIO bucket policy 失败，继续上传。bucket={}, error={}", bucketName, e.getMessage());
        }
    }
}
