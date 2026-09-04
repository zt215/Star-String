package com.graduation.server.controller.dto;

public record CloudModelResponse(
        Long id,
        String owner,
        String kind,
        String name,
        String originalFilename,
        long size,
        String createdAt
) {
}
