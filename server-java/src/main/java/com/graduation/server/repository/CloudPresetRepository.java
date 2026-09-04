package com.graduation.server.repository;

import com.graduation.server.entity.CloudPreset;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface CloudPresetRepository extends JpaRepository<CloudPreset, Long> {

    List<CloudPreset> findByOwnerAndKindOrderByCreatedAtDesc(String owner, String kind);

    Optional<CloudPreset> findByIdAndOwner(Long id, String owner);
}
