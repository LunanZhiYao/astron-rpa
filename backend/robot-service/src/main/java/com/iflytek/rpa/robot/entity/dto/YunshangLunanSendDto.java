package com.iflytek.rpa.robot.entity.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class YunshangLunanSendDto {

    @JsonProperty("receiver_id")
    private String receiverId;

    /** Text 或 File */
    @JsonProperty("msg_type")
    private String msgType;

    @JsonProperty("text")
    private String text;

    @JsonProperty("link")
    private String link;

    @JsonProperty("file_name")
    private String fileName;

    @JsonProperty("file_size")
    private String fileSize;
}
