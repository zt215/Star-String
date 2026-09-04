package com.graduation.server.controller.dto;

public record CloudPresetRequest(
        String owner,
        String kind,
        String name,
        String content
) {
}
