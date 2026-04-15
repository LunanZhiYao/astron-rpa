package com.iflytek.rpa.robot.controller;

import com.iflytek.rpa.robot.entity.vo.MinioUploadResultVo;
import com.iflytek.rpa.robot.service.MinioFileUploadService;
import com.iflytek.rpa.utils.response.AppResponse;
import javax.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/minio")
public class MinioFileUploadController {

    @Resource
    private MinioFileUploadService minioFileUploadService;

    @PostMapping("/upload-file")
    public AppResponse<MinioUploadResultVo> upload(
            @RequestParam("file") MultipartFile file, @RequestParam(value = "object_name", required = false) String objectName) {
        return AppResponse.success(minioFileUploadService.upload(file, objectName));
    }
}
