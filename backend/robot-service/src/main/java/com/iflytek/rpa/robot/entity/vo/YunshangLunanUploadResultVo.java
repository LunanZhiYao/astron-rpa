package com.iflytek.rpa.robot.entity.vo;

import lombok.Data;

@Data
public class YunshangLunanUploadResultVo {
    /** 云上鲁南返回并解密得到的文件链接 */
    private String fileUrl;

    /** 上传的原始文件名 */
    private String fileName;

    /** 上传文件大小（字节） */
    private Long fileSize;
}
