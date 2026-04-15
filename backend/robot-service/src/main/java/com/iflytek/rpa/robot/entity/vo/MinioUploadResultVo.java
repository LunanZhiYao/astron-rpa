package com.iflytek.rpa.robot.entity.vo;

import lombok.Data;

@Data
public class MinioUploadResultVo {
    private String fileUrl;
    private String fileName;
    private Long fileSize;
}
